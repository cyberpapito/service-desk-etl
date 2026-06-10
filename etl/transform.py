"""
transform.py
------------
All transformation logic for the Service Desk ETL pipeline.

ETL Phase: TRANSFORM
Responsibilities:
  - Remove duplicates
  - Handle null/missing values
  - Normalize technician names (messy → canonical)
  - Standardize priorities
  - Standardize categories
  - Calculate SLA compliance
  - Calculate ticket aging metrics
  - Build dimension keys for star schema loading

Every function is documented for portfolio clarity.
"""

import pandas as pd
import numpy as np
import re
import logging

logger = logging.getLogger(__name__)

# ── Technician Name Normalization Map ─────────────────────────────────────────
# Real-world service desks have inconsistent technician entries across tickets,
# imports, and integrations. We map all known variants to a canonical display name.
TECHNICIAN_CANONICAL = {
    # John Smith variants
    "john.smith":  "John Smith",
    "j. smith":    "John Smith",
    "john smith":  "John Smith",
    "john.smith":  "John Smith",
    # Maria Garcia variants
    "maria.garcia": "Maria Garcia",
    "maria garcia": "Maria Garcia",
    "m.garcia":     "Maria Garcia",
    # Dev Patel variants
    "dev.patel":  "Dev Patel",
    "dev patel":  "Dev Patel",
    "d. patel":   "Dev Patel",
    # Sarah Jones variants
    "sarah.jones": "Sarah Jones",
    "s.jones":     "Sarah Jones",
    "sjones":      "Sarah Jones",
    # Mike Chen variants
    "mike.chen": "Mike Chen",
    "m. chen":   "Mike Chen",
    "mchen":     "Mike Chen",
    # Lisa Brown variants
    "lisa.brown": "Lisa Brown",
    "lisa b.":    "Lisa Brown",
    "l.brown":    "Lisa Brown",
    # Tom Wilson variants
    "tom.wilson": "Tom Wilson",
    "t. wilson":  "Tom Wilson",
}

# ── Priority Normalization Map ────────────────────────────────────────────────
PRIORITY_CANONICAL = {
    "p1-critical": "P1-Critical",
    "p2-high":     "P2-High",
    "p3-medium":   "P3-Medium",
    "p4-low":      "P4-Low",
    "critical":    "P1-Critical",
    "high":        "P2-High",
    "medium":      "P3-Medium",
    "low":         "P4-Low",
    "urgent":      "P1-Critical",   # common alias
    "1":           "P1-Critical",
    "2":           "P2-High",
    "3":           "P3-Medium",
    "4":           "P4-Low",
}

SLA_HOURS = {
    "P1-Critical": 4,
    "P2-High":     24,
    "P3-Medium":   72,
    "P4-Low":      168,
}


# ── Step 1: Parse & Type Cast ─────────────────────────────────────────────────

def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert created_at / resolved_at columns to proper datetime objects.
    Coerce errors to NaT rather than raising — bad dates become nulls we
    can report on rather than crash on.
    """
    df = df.copy()
    df["created_at"]  = pd.to_datetime(df["created_at"],  errors="coerce")
    df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce")
    bad_dates = df["created_at"].isna().sum()
    if bad_dates:
        logger.warning(f"  {bad_dates} rows had unparseable created_at — set to NaT")
    return df


# ── Step 2: Deduplication ─────────────────────────────────────────────────────

def remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop exact duplicate rows keeping first occurrence.
    Also deduplicate by ticket_id — a ticket should appear once.
    Logs the count removed for audit trail.
    """
    before = len(df)
    df = df.drop_duplicates()
    df = df.drop_duplicates(subset=["ticket_id"], keep="first")
    removed = before - len(df)
    logger.info(f"  Deduplication removed {removed} rows ({before} → {len(df)})")
    return df


# ── Step 3: Null Handling ─────────────────────────────────────────────────────

def handle_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strategy by column:
      - technician  → fill with 'Unassigned'
      - department  → fill with 'Unknown'
      - priority    → fill with 'P3-Medium' (safe default)
      - category    → fill with 'Other'
      - resolved_at → leave as NaT (open tickets legitimately have no resolution)
    """
    df = df.copy()
    fill_map = {
        "technician": "Unassigned",
        "department": "Unknown",
        "priority":   "P3-Medium",
        "category":   "Other",
    }
    for col, fill_val in fill_map.items():
        nulls = df[col].isna().sum()
        if nulls:
            logger.info(f"  Filling {nulls} nulls in '{col}' with '{fill_val}'")
        df[col] = df[col].fillna(fill_val)
    return df


# ── Step 4: Normalize Technician Names ───────────────────────────────────────

def normalize_technicians(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply TECHNICIAN_CANONICAL lookup after lowercasing and stripping whitespace.
    Any name not in the map is title-cased as a best-effort fallback.
    This mirrors what real ETL pipelines do when ingesting from multiple
    source systems (ITSM, HR system, AD) with different name formats.
    """
    df = df.copy()

    def _normalize(name: str) -> str:
        if pd.isna(name) or name == "Unassigned":
            return "Unassigned"
        key = name.strip().lower()
        return TECHNICIAN_CANONICAL.get(key, name.strip().title())

    df["technician"] = df["technician"].apply(_normalize)
    return df


# ── Step 5: Normalize Priorities ─────────────────────────────────────────────

def normalize_priorities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Map all priority variants to P1-Critical / P2-High / P3-Medium / P4-Low.
    Unknown values fall back to P3-Medium and are logged.
    """
    df = df.copy()

    def _normalize(val: str) -> str:
        if pd.isna(val):
            return "P3-Medium"
        key = str(val).strip().lower()
        result = PRIORITY_CANONICAL.get(key)
        if result is None:
            logger.warning(f"  Unknown priority value '{val}' → defaulting to P3-Medium")
            return "P3-Medium"
        return result

    df["priority"] = df["priority"].apply(_normalize)
    return df


# ── Step 6: SLA Calculations ──────────────────────────────────────────────────

def calculate_sla(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds three SLA columns:
      sla_target_hours  : target hours by priority
      resolution_hours  : actual hours from open → resolved (NaN if unresolved)
      sla_met           : True/False/None (None = ticket still open)

    SLA compliance is a critical KPI for service desk managers and a common
    metric on executive dashboards.
    """
    df = df.copy()
    df["sla_target_hours"] = df["priority"].map(SLA_HOURS)

    # Recalculate resolution_hours from timestamps for accuracy
    mask_resolved = df["resolved_at"].notna() & df["created_at"].notna()
    df["resolution_hours"] = np.nan
    df.loc[mask_resolved, "resolution_hours"] = (
        (df.loc[mask_resolved, "resolved_at"] - df.loc[mask_resolved, "created_at"])
        .dt.total_seconds() / 3600
    ).round(2)

    # SLA met = resolved within target hours
    df["sla_met"] = np.where(
        df["resolution_hours"].notna(),
        df["resolution_hours"] <= df["sla_target_hours"],
        np.nan
    )
    return df


# ── Step 7: Aging Metrics ─────────────────────────────────────────────────────

def calculate_aging(df: pd.DataFrame, as_of: pd.Timestamp = None) -> pd.DataFrame:
    """
    Ticket aging = how long a ticket has been open (or was open before close).
    Useful for identifying stale tickets and workload distribution.

    as_of defaults to today if not provided.
    """
    df = df.copy()
    as_of = as_of or pd.Timestamp.now()

    # For resolved tickets: age = resolution_hours
    # For open tickets: age = hours since created_at
    df["age_hours"] = np.where(
        df["resolved_at"].notna(),
        df["resolution_hours"],
        (as_of - df["created_at"]).dt.total_seconds() / 3600
    )
    df["age_hours"] = df["age_hours"].round(2)

    # Age buckets for dashboard binning
    bins   = [0, 4, 24, 72, 168, float("inf")]
    labels = ["< 4h", "4–24h", "1–3 days", "3–7 days", "> 7 days"]
    df["age_bucket"] = pd.cut(df["age_hours"], bins=bins, labels=labels, right=False)
    df["age_bucket"] = df["age_bucket"].astype(str)

    return df


# ── Step 8: Date Dimensions ───────────────────────────────────────────────────

def add_date_dimensions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Explode created_at into reporting-friendly dimension columns.
    These columns power time-intelligence calculations in Power BI.
    """
    df = df.copy()
    df["created_year"]    = df["created_at"].dt.year
    df["created_month"]   = df["created_at"].dt.month
    df["created_month_name"] = df["created_at"].dt.strftime("%b")
    df["created_quarter"] = df["created_at"].dt.quarter.map(lambda q: f"Q{q}")
    df["created_weekday"] = df["created_at"].dt.day_name()
    df["created_week"]    = df["created_at"].dt.isocalendar().week.astype(int)
    df["created_date"]    = df["created_at"].dt.date.astype(str)
    return df


# ── Master Transform Pipeline ─────────────────────────────────────────────────

def run_transforms(df: pd.DataFrame) -> pd.DataFrame:
    """
    Orchestrates all transformation steps in order.
    Returns the fully cleaned, enriched DataFrame ready for loading.
    """
    logger.info("Starting transformation pipeline...")

    df = parse_dates(df)
    logger.info("  ✓ Parsed dates")

    df = remove_duplicates(df)
    logger.info("  ✓ Removed duplicates")

    df = handle_nulls(df)
    logger.info("  ✓ Handled nulls")

    df = normalize_technicians(df)
    logger.info("  ✓ Normalized technician names")

    df = normalize_priorities(df)
    logger.info("  ✓ Normalized priorities")

    df = calculate_sla(df)
    logger.info("  ✓ Calculated SLA metrics")

    df = calculate_aging(df)
    logger.info("  ✓ Calculated aging metrics")

    df = add_date_dimensions(df)
    logger.info("  ✓ Added date dimensions")

    logger.info(f"Transform complete — {len(df):,} rows ready for load")
    return df
