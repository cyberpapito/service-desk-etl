-- =============================================================================
-- Service Desk Analytics — Database Schema
-- =============================================================================
-- Architecture : Star Schema (Kimball methodology)
-- Database     : SQLite (production upgrade path: PostgreSQL / Snowflake)
-- Author       : Service Desk ETL Pipeline
-- =============================================================================
--
-- STAR SCHEMA OVERVIEW
--
--                    dim_technician
--                          │
--   dim_category ──── fact_tickets ──── dim_department
--                          │
--                    dim_priority
--
-- The fact table holds one row per ticket with foreign keys into four
-- dimension tables. This design:
--   • Enables fast GROUP BY aggregations (each dimension is a simple join)
--   • Supports Power BI relationship modeling (one-to-many from dim → fact)
--   • Scales cleanly to Snowflake / BigQuery with zero schema changes
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Dimension: Technicians
-- Canonical technician names after ETL normalization.
-- Supports: workload reporting, performance dashboards
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_technician (
    technician_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    technician_name  TEXT    NOT NULL UNIQUE
);


-- -----------------------------------------------------------------------------
-- Dimension: Departments
-- Business unit / department that submitted the ticket.
-- Supports: department trend analysis, cost allocation
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_department (
    department_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    department_name  TEXT    NOT NULL UNIQUE
);


-- -----------------------------------------------------------------------------
-- Dimension: Categories
-- Issue category. Allows grouping tickets by type for trend analysis.
-- Future: add sub_category column for two-level hierarchy.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_category (
    category_key    INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name   TEXT    NOT NULL UNIQUE
);


-- -----------------------------------------------------------------------------
-- Dimension: Priorities
-- Ticket priority with associated SLA target in hours.
-- Decoupling SLA from the fact table lets you update SLA targets without
-- touching historical fact records.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_priority (
    priority_key    INTEGER PRIMARY KEY AUTOINCREMENT,
    priority_label  TEXT    NOT NULL UNIQUE,
    sla_hours       INTEGER NOT NULL
);

-- Seed priority dimension with known values
INSERT OR IGNORE INTO dim_priority (priority_label, sla_hours) VALUES ('P1-Critical', 4);
INSERT OR IGNORE INTO dim_priority (priority_label, sla_hours) VALUES ('P2-High',     24);
INSERT OR IGNORE INTO dim_priority (priority_label, sla_hours) VALUES ('P3-Medium',   72);
INSERT OR IGNORE INTO dim_priority (priority_label, sla_hours) VALUES ('P4-Low',      168);


-- -----------------------------------------------------------------------------
-- Fact Table: Tickets
-- One row per service desk ticket. Central table of the star schema.
-- Numeric measures drive all KPI calculations in Power BI.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_tickets (
    -- Natural key from source system
    ticket_id            TEXT    PRIMARY KEY,

    -- Timestamps (stored as ISO-8601 strings for SQLite compatibility)
    created_at           TEXT,
    resolved_at          TEXT,

    -- Ticket state
    status               TEXT    CHECK (status IN (
                                    'Open', 'In Progress', 'Pending',
                                    'Resolved', 'Closed'
                                  )),

    -- ── Foreign Keys into Dimensions ──────────────────────────────────────
    technician_key       INTEGER REFERENCES dim_technician(technician_key),
    department_key       INTEGER REFERENCES dim_department(department_key),
    category_key         INTEGER REFERENCES dim_category(category_key),
    priority_key         INTEGER REFERENCES dim_priority(priority_key),

    -- Free-text subject (for search / display)
    subject              TEXT,

    -- ── Measures ──────────────────────────────────────────────────────────
    resolution_hours     REAL,        -- NULL if ticket still open
    sla_target_hours     INTEGER,     -- copied from dim_priority at load time
    sla_met              INTEGER,     -- 1 = within SLA, 0 = breached, NULL = open
    age_hours            REAL,        -- hours from creation to now (or resolution)
    age_bucket           TEXT,        -- '< 4h', '4–24h', '1–3 days', etc.

    -- ── Denormalized Date Dimensions ──────────────────────────────────────
    -- Stored on the fact for Power BI performance — avoids a separate date dim join
    created_year         INTEGER,
    created_month        INTEGER,
    created_month_name   TEXT,
    created_quarter      TEXT,
    created_weekday      TEXT,
    created_week         INTEGER,
    created_date         TEXT,

    -- ── Audit ─────────────────────────────────────────────────────────────
    loaded_at            TEXT DEFAULT (datetime('now'))
);


-- -----------------------------------------------------------------------------
-- Indexes — dramatically speed up GROUP BY and JOIN operations
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_fact_created_date   ON fact_tickets (created_date);
CREATE INDEX IF NOT EXISTS idx_fact_created_year   ON fact_tickets (created_year, created_month);
CREATE INDEX IF NOT EXISTS idx_fact_status         ON fact_tickets (status);
CREATE INDEX IF NOT EXISTS idx_fact_sla_met        ON fact_tickets (sla_met);
CREATE INDEX IF NOT EXISTS idx_fact_technician     ON fact_tickets (technician_key);
CREATE INDEX IF NOT EXISTS idx_fact_department     ON fact_tickets (department_key);
CREATE INDEX IF NOT EXISTS idx_fact_category       ON fact_tickets (category_key);
CREATE INDEX IF NOT EXISTS idx_fact_priority       ON fact_tickets (priority_key);
