# tests/test_pipeline.py
# Runs the generator and the full pipeline in an empty folder, the way a fresh clone would.
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd

from etl.generate_data import generate_tickets
from etl.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parent.parent


def test_fresh_clone_cli_runs(tmp_path):
    """No data/ folder exists yet: generate_data.py then pipeline.py must both succeed."""
    for script in ("generate_data.py", "pipeline.py"):
        r = subprocess.run([sys.executable, str(ROOT / "etl" / script)],
                           cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    assert (tmp_path / "data" / "processed" / "service_desk.db").exists()
    assert (tmp_path / "data" / "processed" / "etl.log").read_text().count("PIPELINE COMPLETE") == 1


def test_generated_sla_targets_match_priority():
    df = generate_tickets(500)
    expected = {"P1-Critical": 4, "P2-High": 24, "P3-Medium": 72, "P4-Low": 168, "URGENT": 72}
    assert (df["sla_target_hours"] == df["priority"].map(expected)).all()
    assert df["sla_target_hours"].nunique() > 1


def test_pipeline_loads_star_schema_and_is_rerunnable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logging.disable(logging.CRITICAL)
    try:
        raw_dir = tmp_path / "data" / "raw"
        raw_dir.mkdir(parents=True)
        generate_tickets(300).to_csv(raw_dir / "tickets_raw.csv", index=False)
        db = os.path.join("data", "processed", "service_desk.db")

        for _ in range(2):   # second run must not duplicate anything
            run_pipeline(str(raw_dir / "tickets_raw.csv"), db, archive=False,
                         as_of=pd.Timestamp("2024-12-31"))
    finally:
        logging.disable(logging.NOTSET)

    c = sqlite3.connect(db)
    one = lambda q: c.execute(q).fetchone()[0]
    assert one("SELECT COUNT(*) FROM fact_tickets") == 300
    assert one("SELECT COUNT(*) FROM dim_priority") == 4
    assert one("SELECT COUNT(*) FROM dim_technician") == 8          # 7 people + Unassigned
    assert one("SELECT COUNT(*) FROM fact_tickets WHERE technician_key IS NULL "
               "OR department_key IS NULL OR category_key IS NULL OR priority_key IS NULL") == 0
    assert one("SELECT COUNT(*) FROM fact_tickets WHERE age_bucket = 'nan'") == 0
    # Aged against 2024-12-31, open tickets spread over buckets instead of all being "> 7 days"
    assert one("SELECT COUNT(DISTINCT age_bucket) FROM fact_tickets WHERE resolved_at IS NULL") > 1
    assert one("SELECT COUNT(*) FROM fact_tickets WHERE sla_met IS NULL") == \
        one("SELECT COUNT(*) FROM fact_tickets WHERE resolved_at IS NULL")


def test_reporting_queries_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logging.disable(logging.CRITICAL)
    try:
        (tmp_path / "data" / "raw").mkdir(parents=True)
        generate_tickets(300).to_csv("data/raw/tickets_raw.csv", index=False)
        run_pipeline("data/raw/tickets_raw.csv", "data/processed/service_desk.db", archive=False)
    finally:
        logging.disable(logging.NOTSET)

    c = sqlite3.connect("data/processed/service_desk.db")
    sql = (ROOT / "sql" / "queries" / "reporting_queries.sql").read_text()
    statements = []
    for chunk in sql.split(";"):
        body = "\n".join(l for l in chunk.splitlines() if not l.strip().startswith("--")).strip()
        if body:
            statements.append(body)
    assert len(statements) == 10
    for q in statements:
        assert c.execute(q).fetchall(), q[:80]
