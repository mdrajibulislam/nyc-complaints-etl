"""Paged reader for the NYC Open Data (Socrata) API.

Socrata caps a response at 50k rows, so an extract is a sequence of
$limit/$offset calls. Set SOCRATA_APP_TOKEN to avoid anonymous throttling.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterator

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://data.cityofnewyork.us/resource/{dataset_id}.json"
PAGE_SIZE = 50_000
MAX_RETRIES = 4
BACKOFF_SECONDS = 2.0


class SocrataError(RuntimeError):
    """The API could not be read after all retries."""


class SocrataClient:
    def __init__(self, app_token: str | None = None, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()
        token = app_token or os.environ.get("SOCRATA_APP_TOKEN")
        if token:
            self.session.headers["X-App-Token"] = token
        else:
            log.warning(
                "No SOCRATA_APP_TOKEN set - requests are subject to strict "
                "anonymous throttling. Extraction will still work but is slower."
            )

    def _get(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 429:
                    raise requests.HTTPError("429 rate limited")
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                sleep_for = BACKOFF_SECONDS * (2 ** (attempt - 1))
                log.warning(
                    "Socrata request failed (attempt %d/%d): %s - retrying in %.0fs",
                    attempt,
                    MAX_RETRIES,
                    exc,
                    sleep_for,
                )
                time.sleep(sleep_for)
        raise SocrataError(f"Giving up on {url} after {MAX_RETRIES} attempts") from last_error

    def iter_pages(
        self,
        dataset_id: str,
        select: list[str] | None = None,
        where: str | None = None,
        order: str | None = None,
        max_rows: int | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of rows for a dataset.

        Always pass `order`. Socrata's sort isn't stable across paged requests
        without one, and you get duplicate and missing rows with no warning.
        """
        url = BASE_URL.format(dataset_id=dataset_id)
        offset = 0
        fetched = 0

        while True:
            page_size = PAGE_SIZE
            if max_rows is not None:
                page_size = min(page_size, max_rows - fetched)
                if page_size <= 0:
                    return

            params: dict[str, Any] = {"$limit": page_size, "$offset": offset}
            if select:
                params["$select"] = ",".join(select)
            if where:
                params["$where"] = where
            if order:
                params["$order"] = order

            rows = self._get(url, params)
            if not rows:
                return

            fetched += len(rows)
            offset += len(rows)
            log.info("%s: fetched %d rows (total %d)", dataset_id, len(rows), fetched)
            yield rows

            if len(rows) < page_size:
                return

    def fetch_all(self, dataset_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in self.iter_pages(dataset_id, **kwargs):
            rows.extend(page)
        return rows
