# tests/test_transform.py
import numpy as np
import pandas as pd
import pytest

from etl.transform import (
    add_date_dimensions,
    calculate_aging,
    calculate_sla,
    handle_nulls,
    normalize_priorities,
    normalize_priority_single,
    normalize_technicians,
    parse_dates,
    remove_duplicates,
    run_transforms,
)


def raw(**overrides):
    """One raw ticket row as the CSV extract produces it (all strings)."""
    row = {
        "ticket_id": "TKT-00001",
        "created_at": "2024-03-01 09:00:00",
        "resolved_at": "2024-03-01 11:00:00",
        "status": "Resolved",
        "priority": "P1-Critical",
        "category": "Hardware",
        "subject": "Laptop won't turn on",
        "technician": "john.smith",
        "department": "Finance",
    }
    row.update(overrides)
    return row


# ── Priorities ────────────────────────────────────────────────────────────────

def test_urgent_maps_to_p1():
    assert normalize_priority_single("URGENT") == "P1-Critical"


def test_unknown_defaults_to_p3():
    assert normalize_priority_single("BANANA") == "P3-Medium"


@pytest.mark.parametrize("value, expected", [
    ("urgent", "P1-Critical"), (" 1 ", "P1-Critical"), ("HIGH", "P2-High"),
    ("3", "P3-Medium"), ("p4-low", "P4-Low"), (None, "P3-Medium"),
])
def test_normalize_priorities_column(value, expected):
    df = pd.DataFrame({"priority": [value]})
    assert normalize_priorities(df)["priority"].iloc[0] == expected


# ── Technicians ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("variant", ["john.smith", "J. Smith", "john smith", "JOHN.SMITH", "  John.Smith  "])
def test_john_smith_variants_collapse(variant):
    df = pd.DataFrame({"technician": [variant]})
    assert normalize_technicians(df)["technician"].iloc[0] == "John Smith"


def test_unknown_technician_is_title_cased_and_unassigned_kept():
    df = pd.DataFrame({"technician": ["pat quinn", "Unassigned", None]})
    assert normalize_technicians(df)["technician"].tolist() == ["Pat Quinn", "Unassigned", "Unassigned"]


# ── Dedup and nulls ───────────────────────────────────────────────────────────

def test_remove_duplicates_drops_exact_and_ticket_id_dupes():
    df = pd.DataFrame([raw(), raw(), raw(subject="edited"), raw(ticket_id="TKT-00002")])
    out = remove_duplicates(df)
    assert out["ticket_id"].tolist() == ["TKT-00001", "TKT-00002"]
    assert out["subject"].iloc[0] == "Laptop won't turn on"   # first occurrence wins


def test_handle_nulls_fills_defaults():
    df = pd.DataFrame([raw(technician=None, department=None, priority=None, category=None)])
    out = handle_nulls(df).iloc[0]
    assert (out["technician"], out["department"], out["priority"], out["category"]) == \
        ("Unassigned", "Unknown", "P3-Medium", "Other")


# ── SLA ───────────────────────────────────────────────────────────────────────

def test_sla_met_breached_and_open():
    df = parse_dates(pd.DataFrame([
        raw(ticket_id="met",    priority="P1-Critical", resolved_at="2024-03-01 12:59:00"),  # 3.98h ≤ 4
        raw(ticket_id="breach", priority="P1-Critical", resolved_at="2024-03-01 13:30:00"),  # 4.5h > 4
        raw(ticket_id="open",   priority="P4-Low",      resolved_at=None, status="Open"),
    ]))
    out = calculate_sla(df).set_index("ticket_id")
    assert out.loc["met", "sla_met"] == 1
    assert out.loc["breach", "sla_met"] == 0
    assert np.isnan(out.loc["open", "sla_met"])
    assert out.loc["breach", "resolution_hours"] == 4.5
    assert out.loc["open", "sla_target_hours"] == 168


# ── Aging ─────────────────────────────────────────────────────────────────────

def test_aging_uses_as_of_for_open_tickets_and_resolution_for_closed():
    df = parse_dates(pd.DataFrame([
        raw(ticket_id="closed", resolved_at="2024-03-01 11:00:00"),
        raw(ticket_id="open2d", resolved_at=None, status="Open"),
    ]))
    out = calculate_aging(calculate_sla(df), as_of=pd.Timestamp("2024-03-03 09:00:00")).set_index("ticket_id")
    assert out.loc["closed", "age_hours"] == 2.0
    assert out.loc["closed", "age_bucket"] == "< 4h"
    assert out.loc["open2d", "age_hours"] == 48.0
    assert out.loc["open2d", "age_bucket"] == "1–3 days"


def test_aging_bad_or_future_date_has_no_bucket_not_nan_string():
    df = parse_dates(pd.DataFrame([
        raw(ticket_id="future", created_at="2025-01-05 00:00:00", resolved_at=None, status="Open"),
        raw(ticket_id="bad",    created_at="not a date", resolved_at=None, status="Open"),
    ]))
    out = calculate_aging(calculate_sla(df), as_of=pd.Timestamp("2024-12-31")).set_index("ticket_id")
    assert out.loc["bad", "age_bucket"] is None
    assert out.loc["future", "age_bucket"] is None


# ── Date dimensions ───────────────────────────────────────────────────────────

def test_date_dimensions():
    out = add_date_dimensions(parse_dates(pd.DataFrame([raw(created_at="2024-11-15 08:00:00")]))).iloc[0]
    assert (out["created_year"], out["created_month"], out["created_month_name"],
            out["created_quarter"], out["created_weekday"], out["created_date"]) == \
        (2024, 11, "Nov", "Q4", "Friday", "2024-11-15")


# ── Whole transform ───────────────────────────────────────────────────────────

def test_run_transforms_end_to_end():
    df = pd.DataFrame([
        raw(),
        raw(),                                                        # exact dupe
        raw(ticket_id="TKT-00002", technician="S.Jones", priority="URGENT",
            department=None, resolved_at=None, status="Open"),
    ])
    out = run_transforms(df, as_of=pd.Timestamp("2024-03-02 09:00:00")).set_index("ticket_id")
    assert len(out) == 2
    t2 = out.loc["TKT-00002"]
    assert (t2["technician"], t2["priority"], t2["department"], t2["age_bucket"]) == \
        ("Sarah Jones", "P1-Critical", "Unknown", "1–3 days")
