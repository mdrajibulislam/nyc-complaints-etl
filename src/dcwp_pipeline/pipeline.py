"""Pipeline orchestration: extract, validate, transform, load, analyse."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import analysis, transform
from .quality import QualityReport, run_checks
from .socrata import SocrataClient

log = logging.getLogger(__name__)


@dataclass
class Paths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def warehouse(self) -> Path:
        return self.root / "data" / "warehouse" / "dcwp.db"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    def ensure(self) -> None:
        self.raw.mkdir(parents=True, exist_ok=True)
        self.warehouse.parent.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def extract(config: dict, paths: Paths, max_rows: int | None = None) -> dict[str, pd.DataFrame]:
    """Pull each configured source and cache it as Parquet-free CSV.

    CSV rather than Parquet on purpose: a reviewer can open the cached extract
    in any tool without installing anything, which matters more here than the
    file size.
    """
    client = SocrataClient()
    frames: dict[str, pd.DataFrame] = {}

    for name, spec in config["sources"].items():
        log.info("Extracting %s (%s)", name, spec["description"])
        rows = client.fetch_all(
            spec["dataset_id"],
            select=spec.get("select"),
            order=spec.get("order"),
            max_rows=max_rows,
        )
        df = pd.DataFrame(rows)
        cached = paths.raw / f"{name}.csv"
        df.to_csv(cached, index=False)
        log.info("%s: %d rows cached at %s", name, len(df), cached)
        frames[name] = df

    return frames


def load_cached(config: dict, paths: Paths) -> dict[str, pd.DataFrame]:
    frames = {}
    for name in config["sources"]:
        cached = paths.raw / f"{name}.csv"
        if not cached.exists():
            raise FileNotFoundError(f"No cached extract at {cached}; run `extract` first.")
        frames[name] = pd.read_csv(cached, dtype=str, low_memory=False)
        log.info("%s: %d rows loaded from cache", name, len(frames[name]))
    return frames


def validate(
    frames: dict[str, pd.DataFrame],
    config: dict,
    paths: Paths,
    sampled: bool = False,
) -> QualityReport:
    """Run the declared rules. ``sampled`` relaxes volume floors only.

    A deliberately truncated extract cannot satisfy a row-count minimum, so in
    sample mode those checks drop to ``warn``. Every other rule still applies
    at full strength, and the relaxation is logged rather than silent - a
    quality gate that quietly weakens itself is worse than none.
    """
    rules = config["quality_rules"]
    if sampled:
        import copy as _copy

        rules = _copy.deepcopy(rules)
        relaxed = 0
        for specs in rules.values():
            for spec in specs:
                if spec.get("check") == "row_count_min":
                    spec["severity"] = "warn"
                    relaxed += 1
        log.warning(
            "Sample mode: %d row_count_min check(s) downgraded to warn. "
            "All other rules still enforced at error severity.",
            relaxed,
        )

    report = run_checks(frames, rules)
    report.to_json(paths.reports / "data_quality.json")
    report.to_markdown(paths.reports / "data_quality.md")
    log.info(
        "Quality: %d checks, %d errors, %d warnings -> %s",
        len(report.results), len(report.errors), len(report.warnings),
        "PASS" if report.ok else "FAIL",
    )
    return report


def build_models(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    complaints = transform.clean_complaints(frames["complaints"])
    charges = transform.clean_charges(frames["charges"])
    return {
        "complaints": complaints,
        "charges": charges,
        "complaints_by_category": transform.complaints_by_category(complaints),
        "charges_by_category": transform.charges_by_category(charges),
        "business_bridge": transform.build_business_bridge(complaints, charges),
    }


def write_warehouse(models: dict[str, pd.DataFrame], paths: Paths) -> None:
    import sqlite3

    schema = (paths.root / "sql" / "01_schema.sql").read_text(encoding="utf-8")
    with sqlite3.connect(paths.warehouse) as conn:
        conn.executescript(schema)
        for name, df in models.items():
            df.to_sql(name, conn, if_exists="replace", index=False)
            log.info("warehouse: wrote %s (%d rows)", name, len(df))
        conn.commit()
    log.info("Warehouse at %s", paths.warehouse)


def analyse(models: dict[str, pd.DataFrame], config: dict, paths: Paths) -> pd.DataFrame:
    settings = config["analysis"]
    profile = analysis.category_profile(
        models["complaints_by_category"],
        models["charges_by_category"],
        min_complaints=settings["min_complaints_per_category"],
    )
    summary = analysis.summarise(profile)
    bridge = analysis.bridge_summary(models["business_bridge"])

    profile.to_csv(paths.reports / "category_profile.csv", index=False)
    (paths.reports / "findings.md").write_text(
        analysis.to_markdown(profile, summary, bridge, top_n=settings["top_n"]),
        encoding="utf-8",
    )
    (paths.reports / "summary.json").write_text(
        json.dumps({"categories": summary, "businesses": bridge}, indent=2, default=str),
        encoding="utf-8",
    )
    log.info("Reports written to %s", paths.reports)
    return profile
