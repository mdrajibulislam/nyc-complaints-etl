import pandas as pd

from nyc_complaints_etl.quality import run_checks


def _frames():
    return {
        "complaints": pd.DataFrame(
            {
                "record_id": ["1", "2", "3"],
                "business_unique_id": ["BA-1-2024", None, "BA-3-2024"],
                "intake_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            }
        ),
        "charges": pd.DataFrame(
            {
                "record_id": ["9"],
                "business_unique_id": ["BA-1-2024"],
                "charge_count": ["2"],
            }
        ),
    }


def test_passing_rules_produce_a_clean_report():
    rules = {
        "complaints": [
            {"check": "row_count_min", "min": 3},
            {"check": "unique", "column": "record_id"},
            {"check": "not_null", "column": "record_id"},
        ]
    }
    report = run_checks(_frames(), rules)
    assert report.ok
    assert len(report.results) == 3
    assert not report.failures


def test_error_severity_fails_the_report_and_warn_does_not():
    rules = {
        "complaints": [
            {"check": "not_null", "column": "business_unique_id",
             "max_null_rate": 0.0, "severity": "warn"},
        ]
    }
    report = run_checks(_frames(), rules)
    assert report.ok, "a warn-level failure must not fail the run"
    assert len(report.warnings) == 1

    rules["complaints"][0]["severity"] = "error"
    report = run_checks(_frames(), rules)
    assert not report.ok
    assert len(report.errors) == 1


def test_missing_table_is_an_error_not_a_crash():
    report = run_checks(_frames(), {"nonexistent": [{"check": "row_count_min", "min": 1}]})
    assert not report.ok
    assert report.errors[0].check == "table_present"


def test_missing_column_is_reported_rather_than_raising():
    rules = {"complaints": [{"check": "not_null", "column": "no_such_column"}]}
    report = run_checks(_frames(), rules)
    assert not report.ok
    assert report.errors[0].observed == "column missing"


def test_unknown_check_name_is_surfaced():
    rules = {"complaints": [{"check": "check_i_never_wrote", "column": "record_id"}]}
    report = run_checks(_frames(), rules)
    assert not report.ok
    assert "No implementation registered" in report.errors[0].message


def test_referential_integrity_detects_orphans():
    rules = {
        "charges": [
            {"check": "referential_integrity", "column": "business_unique_id",
             "references": "complaints.business_unique_id", "max_orphan_rate": 0.0,
             "severity": "error"}
        ]
    }
    report = run_checks(_frames(), rules)
    assert report.ok, "BA-1-2024 exists on both sides"

    frames = _frames()
    frames["charges"].loc[0, "business_unique_id"] = "BA-999-2024"
    report = run_checks(frames, rules)
    assert not report.ok


def test_accepted_values_flags_out_of_domain(tmp_path):
    frames = _frames()
    frames["charges"]["outcome"] = ["Surprise Outcome"]
    rules = {
        "charges": [
            {"check": "accepted_values", "column": "outcome",
             "values": ["Pleaded", "Default Decision"], "max_violation_rate": 0.0}
        ]
    }
    report = run_checks(frames, rules)
    assert not report.ok

    report.to_json(tmp_path / "q.json")
    report.to_markdown(tmp_path / "q.md")
    assert (tmp_path / "q.json").exists()
    assert "FAIL" in (tmp_path / "q.md").read_text()
