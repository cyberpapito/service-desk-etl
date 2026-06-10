"""
load.py
-------
Loads transformed data into SQLite (star schema).

ETL Phase: LOAD
Responsibilities:
  - Create database tables if they don't exist
  - Upsert dimension tables (idempotent)
  - Insert fact records
  - Log row counts for audit trail

Design pattern: star schema with one fact table + four dimension tables.
This mirrors what you'd build in Snowflake, BigQuery, or SQL Server for
a production BI environment.
"""

import sqlite3
import pandas as pd
import logging
import os

logger = logging.getLogger(__name__)

DB_PATH = os.path.join("data", "processed", "service_desk.db")


# ── Schema DDL ────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- ─────────────────────────────────────────────────────────────────────────────
-- Dimension: Technicians
-- One row per unique technician. Supports technician-level reporting.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_technician (
    technician_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    technician_name  TEXT    NOT NULL UNIQUE
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Dimension: Departments
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_department (
    department_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    department_name  TEXT    NOT NULL UNIQUE
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Dimension: Categories
-- Allows category hierarchy expansion (e.g. category → sub-category) later.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_category (
    category_key    INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name   TEXT    NOT NULL UNIQUE
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Dimension: Priorities
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_priority (
    priority_key    INTEGER PRIMARY KEY AUTOINCREMENT,
    priority_label  TEXT    NOT NULL UNIQUE,
    sla_hours       INTEGER NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Fact Table: Tickets
-- One row per ticket. Foreign keys into all dimension tables.
-- Numeric measures: resolution_hours, age_hours, sla_target_hours.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_tickets (
    ticket_id           TEXT    PRIMARY KEY,
    created_at          TEXT,
    resolved_at         TEXT,
    status              TEXT,

    -- Foreign Keys
    technician_key      INTEGER REFERENCES dim_technician(technician_key),
    department_key      INTEGER REFERENCES dim_department(department_key),
    category_key        INTEGER REFERENCES dim_category(category_key),
    priority_key        INTEGER REFERENCES dim_priority(priority_key),

    -- Subject / description
    subject             TEXT,

    -- Measures
    resolution_hours    REAL,
    sla_target_hours    INTEGER,
    sla_met             INTEGER,   -- 1=True, 0=False, NULL=open
    age_hours           REAL,
    age_bucket          TEXT,

    -- Date dimensions (denormalized for Power BI / query performance)
    created_year        INTEGER,
    created_month       INTEGER,
    created_month_name  TEXT,
    created_quarter     TEXT,
    created_weekday     TEXT,
    created_week        INTEGER,
    created_date        TEXT,

    loaded_at           TEXT DEFAULT (datetime('now'))
);
"""


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_schema(conn: sqlite3.Connection):
    """Create all tables if they don't exist. Safe to run on every pipeline execution."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    logger.info("  ✓ Schema initialized")


# ── Dimension Loaders (Upsert Pattern) ───────────────────────────────────────

def load_dim_technician(conn: sqlite3.Connection, df: pd.DataFrame) -> dict:
    """Insert new technicians; return name → key mapping."""
    names = df["technician"].dropna().unique()
    for name in names:
        conn.execute(
            "INSERT OR IGNORE INTO dim_technician (technician_name) VALUES (?)", (name,)
        )
    conn.commit()
    cursor = conn.execute("SELECT technician_name, technician_key FROM dim_technician")
    return {row[0]: row[1] for row in cursor.fetchall()}


def load_dim_department(conn: sqlite3.Connection, df: pd.DataFrame) -> dict:
    depts = df["department"].dropna().unique()
    for d in depts:
        conn.execute(
            "INSERT OR IGNORE INTO dim_department (department_name) VALUES (?)", (d,)
        )
    conn.commit()
    cursor = conn.execute("SELECT department_name, department_key FROM dim_department")
    return {row[0]: row[1] for row in cursor.fetchall()}


def load_dim_category(conn: sqlite3.Connection, df: pd.DataFrame) -> dict:
    cats = df["category"].dropna().unique()
    for c in cats:
        conn.execute(
            "INSERT OR IGNORE INTO dim_category (category_name) VALUES (?)", (c,)
        )
    conn.commit()
    cursor = conn.execute("SELECT category_name, category_key FROM dim_category")
    return {row[0]: row[1] for row in cursor.fetchall()}


def load_dim_priority(conn: sqlite3.Connection, df: pd.DataFrame) -> dict:
    from etl.transform import SLA_HOURS
    for label, hours in SLA_HOURS.items():
        conn.execute(
            "INSERT OR IGNORE INTO dim_priority (priority_label, sla_hours) VALUES (?, ?)",
            (label, hours)
        )
    conn.commit()
    cursor = conn.execute("SELECT priority_label, priority_key FROM dim_priority")
    return {row[0]: row[1] for row in cursor.fetchall()}


# ── Fact Table Loader ─────────────────────────────────────────────────────────

def load_fact_tickets(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    tech_map:  dict,
    dept_map:  dict,
    cat_map:   dict,
    prio_map:  dict,
):
    """
    Maps dimension keys onto the fact DataFrame then bulk-inserts into fact_tickets.
    Uses INSERT OR REPLACE to make the load idempotent — safe to re-run.
    """
    df = df.copy()
    df["technician_key"] = df["technician"].map(tech_map)
    df["department_key"] = df["department"].map(dept_map)
    df["category_key"]   = df["category"].map(cat_map)
    df["priority_key"]   = df["priority"].map(prio_map)

    # Convert bool/NaN sla_met to 1/0/NULL for SQLite
    df["sla_met"] = df["sla_met"].apply(
        lambda v: 1 if v is True or v == 1.0
        else (0 if v is False or v == 0.0 else None)
    )

    # Stringify timestamps for SQLite
    for col in ("created_at", "resolved_at"):
        df[col] = df[col].astype(str).replace("NaT", None)

    cols = [
        "ticket_id", "created_at", "resolved_at", "status",
        "technician_key", "department_key", "category_key", "priority_key",
        "subject", "resolution_hours", "sla_target_hours", "sla_met",
        "age_hours", "age_bucket",
        "created_year", "created_month", "created_month_name",
        "created_quarter", "created_weekday", "created_week", "created_date",
    ]

    # Only include columns that exist in the dataframe
    cols = [c for c in cols if c in df.columns]
    rows = df[cols].to_dict(orient="records")

    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    sql = f"INSERT OR REPLACE INTO fact_tickets ({col_str}) VALUES ({placeholders})"

    conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    conn.commit()
    logger.info(f"  ✓ Loaded {len(rows):,} rows into fact_tickets")


# ── Master Load Orchestrator ──────────────────────────────────────────────────

def run_load(df: pd.DataFrame, db_path: str = DB_PATH):
    logger.info(f"Starting load → {db_path}")
    conn = get_connection(db_path)

    initialize_schema(conn)

    tech_map = load_dim_technician(conn, df)
    dept_map = load_dim_department(conn, df)
    cat_map  = load_dim_category(conn, df)
    prio_map = load_dim_priority(conn, df)
    logger.info(f"  ✓ Dimensions loaded — {len(tech_map)} techs, {len(dept_map)} depts, "
                f"{len(cat_map)} categories, {len(prio_map)} priorities")

    load_fact_tickets(conn, df, tech_map, dept_map, cat_map, prio_map)

    conn.close()
    logger.info("Load complete ✓")
