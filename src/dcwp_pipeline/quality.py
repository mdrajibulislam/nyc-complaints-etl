"""A small declarative data-quality framework.

Checks are declared as data (see ``config/pipeline.json``) rather than written
as one-off assertions, so a reviewer can see every rule the pipeline enforces
in one place and add a rule without touching Python.

Each check returns a :class:`CheckResult`. Results at ``error`` severity fail
the run; ``warn`` results are recorded and reported but do not stop the
pipeline. The distinction matters on public data, where a handful of malformed
rows is normal and a 40% null rate in a key column is not.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class CheckResult:
    table: str
    check: str
    column: str | None
    severity: str
    passed: bool
    observed: Any
    threshold: Any
    message: str


@dataclass
class QualityReport:
    generated_at: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    @property
    def errors(self) -> list[CheckResult]:
        return [r for r in self.failures if r.severity == "error"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.failures if r.severity == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": self.generated_at,
            "ok": self.ok,
            "total_checks": len(self.results),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "results": [asdict(r) for r in self.results],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def to_markdown(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Data quality report",
            "",
            f"Generated: {self.generated_at}",
            "",
            f"- Checks run: **{len(self.results)}**",
            f"- Errors: **{len(self.errors)}**",
            f"- Warnings: **{len(self.warnings)}**",
            f"- Verdict: **{'PASS' if self.ok else 'FAIL'}**",
            "",
            "| Table | Check | Column | Severity | Result | Observed | Threshold |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in self.results:
            lines.append(
                f"| {r.table} | {r.check} | {r.column or '-'} | {r.severity} | "
                f"{'pass' if r.passed else 'FAIL'} | {r.observed} | {r.threshold} |"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Individual check implementations
# --------------------------------------------------------------------------

def _row_count_min(df: pd.DataFrame, spec: dict, table: str) -> CheckResult:
    threshold = spec["min"]
    observed = len(df)
    return CheckResult(
        table, "row_count_min", None, spec.get("severity", "error"),
        observed >= threshold, observed, threshold,
        f"{table} has {observed} rows (minimum {threshold})",
    )


def _not_null(df: pd.DataFrame, spec: dict, table: str) -> CheckResult:
    column = spec["column"]
    threshold = spec.get("max_null_rate", 0.0)
    if column not in df.columns:
        return CheckResult(
            table, "not_null", column, "error", False, "column missing", threshold,
            f"{table}.{column} is absent from the extract",
        )
    observed = float(df[column].isna().mean()) if len(df) else 0.0
    return CheckResult(
        table, "not_null", column, spec.get("severity", "error"),
        observed <= threshold, round(observed, 4), threshold,
        f"{table}.{column} null rate {observed:.2%} (max {threshold:.2%})",
    )


def _unique(df: pd.DataFrame, spec: dict, table: str) -> CheckResult:
    column = spec["column"]
    if column not in df.columns:
        return CheckResult(
            table, "unique", column, "error", False, "column missing", 0,
            f"{table}.{column} is absent from the extract",
        )
    duplicates = int(df[column].duplicated().sum())
    threshold = spec.get("max_duplicates", 0)
    return CheckResult(
        table, "unique", column, spec.get("severity", "error"),
        duplicates <= threshold, duplicates, threshold,
        f"{table}.{column} has {duplicates} duplicate values (max {threshold})",
    )


def _accepted_values(df: pd.DataFrame, spec: dict, table: str) -> CheckResult:
    column = spec["column"]
    allowed = set(spec["values"])
    threshold = spec.get("max_violation_rate", 0.0)
    if column not in df.columns:
        return CheckResult(
            table, "accepted_values", column, "error", False, "column missing", threshold,
            f"{table}.{column} is absent from the extract",
        )
    present = df[column].dropna()
    bad = (~present.isin(allowed)).mean() if len(present) else 0.0
    observed = float(bad)
    return CheckResult(
        table, "accepted_values", column, spec.get("severity", "error"),
        observed <= threshold, round(observed, 4), threshold,
        f"{table}.{column} has {observed:.2%} values outside {sorted(allowed)}",
    )


def _unique_composite(df: pd.DataFrame, spec: dict, table: str) -> CheckResult:
    """Uniqueness across a column set, for tables whose grain is composite."""
    columns = spec["columns"]
    label = " + ".join(columns)
    missing = [c for c in columns if c not in df.columns]
    if missing:
        return CheckResult(
            table, "unique_composite", label, "error", False, f"missing {missing}", 0,
            f"{table} is missing {missing} from the extract",
        )
    duplicates = int(df.duplicated(subset=columns).sum())
    threshold = spec.get("max_duplicates", 0)
    return CheckResult(
        table, "unique_composite", label, spec.get("severity", "error"),
        duplicates <= threshold, duplicates, threshold,
        f"{table} has {duplicates} duplicate ({label}) rows (max {threshold})",
    )


def _referential_integrity(
    df: pd.DataFrame, spec: dict, table: str, frames: dict[str, pd.DataFrame]
) -> CheckResult:
    column = spec["column"]
    ref_table, ref_column = spec["references"].split(".")
    threshold = spec.get("max_orphan_rate", 0.0)

    if ref_table not in frames:
        return CheckResult(
            table, "referential_integrity", column, "error", False,
            f"missing table {ref_table}", threshold,
            f"Reference table {ref_table} was not extracted",
        )

    left = df[column].dropna()
    right = set(frames[ref_table][ref_column].dropna())
    observed = float((~left.isin(right)).mean()) if len(left) else 0.0
    return CheckResult(
        table, "referential_integrity", column, spec.get("severity", "warn"),
        observed <= threshold, round(observed, 4), threshold,
        f"{observed:.2%} of {table}.{column} have no match in {ref_table}.{ref_column}",
    )


def _date_not_future(df: pd.DataFrame, spec: dict, table: str) -> CheckResult:
    column = spec["column"]
    threshold = spec.get("max_violation_rate", 0.0)
    if column not in df.columns:
        return CheckResult(
            table, "date_not_future", column, "error", False, "column missing", threshold,
            f"{table}.{column} is absent from the extract",
        )
    parsed = pd.to_datetime(df[column], errors="coerce")
    now = pd.Timestamp.now()
    valid = parsed.dropna()
    observed = float((valid > now).mean()) if len(valid) else 0.0
    return CheckResult(
        table, "date_not_future", column, spec.get("severity", "warn"),
        observed <= threshold, round(observed, 4), threshold,
        f"{observed:.2%} of {table}.{column} are in the future",
    )


def _numeric_range(df: pd.DataFrame, spec: dict, table: str) -> CheckResult:
    column = spec["column"]
    lo, hi = spec.get("min"), spec.get("max")
    threshold = spec.get("max_violation_rate", 0.0)
    if column not in df.columns:
        return CheckResult(
            table, "numeric_range", column, "error", False, "column missing", threshold,
            f"{table}.{column} is absent from the extract",
        )
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if not len(values):
        observed = 0.0
    else:
        out = pd.Series(False, index=values.index)
        if lo is not None:
            out |= values < lo
        if hi is not None:
            out |= values > hi
        observed = float(out.mean())
    return CheckResult(
        table, "numeric_range", column, spec.get("severity", "warn"),
        observed <= threshold, round(observed, 4), threshold,
        f"{observed:.2%} of {table}.{column} fall outside [{lo}, {hi}]",
    )


CHECKS: dict[str, Callable[..., CheckResult]] = {
    "row_count_min": _row_count_min,
    "not_null": _not_null,
    "unique": _unique,
    "unique_composite": _unique_composite,
    "accepted_values": _accepted_values,
    "date_not_future": _date_not_future,
    "numeric_range": _numeric_range,
}

NEEDS_FRAMES = {"referential_integrity": _referential_integrity}


def run_checks(
    frames: dict[str, pd.DataFrame], rules: dict[str, list[dict]]
) -> QualityReport:
    """Run every declared rule against the extracted frames."""
    report = QualityReport(generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    for table, specs in rules.items():
        df = frames.get(table)
        if df is None:
            report.results.append(
                CheckResult(table, "table_present", None, "error", False, "missing", "present",
                            f"Table {table} was never extracted")
            )
            continue

        for spec in specs:
            name = spec["check"]
            if name in NEEDS_FRAMES:
                result = NEEDS_FRAMES[name](df, spec, table, frames)
            elif name in CHECKS:
                result = CHECKS[name](df, spec, table)
            else:
                result = CheckResult(
                    table, name, spec.get("column"), "error", False, "unknown check", None,
                    f"No implementation registered for check '{name}'",
                )
            level = log.info if result.passed else (
                log.error if result.severity == "error" else log.warning
            )
            level("[%s] %s", "PASS" if result.passed else result.severity.upper(), result.message)
            report.results.append(result)

    return report
