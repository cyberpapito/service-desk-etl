"""
generate_data.py
----------------
Generates realistic synthetic service desk ticket data for the ETL pipeline.
Run once to populate data/raw/ before running the ETL pipeline.

Usage:
    python etl/generate_data.py
"""

import pandas as pd
import numpy as np
import random
import os
from datetime import datetime, timedelta

# ── Reproducibility ──────────────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)

# ── Configuration ─────────────────────────────────────────────────────────────
OUTPUT_DIR = "data/raw"
NUM_TICKETS = 2000
START_DATE  = datetime(2024, 1, 1)
END_DATE    = datetime(2024, 12, 31)

# ── Reference Data ────────────────────────────────────────────────────────────
CATEGORIES = [
    "Hardware", "Software", "Network", "Access / Identity",
    "Email", "Printing", "VPN", "Security", "Onboarding", "Other"
]

PRIORITIES = ["P1-Critical", "P2-High", "P3-Medium", "P4-Low"]
PRIORITY_WEIGHTS = [0.05, 0.15, 0.50, 0.30]

STATUSES = ["Resolved", "Closed", "Open", "In Progress", "Pending"]
STATUS_WEIGHTS = [0.55, 0.25, 0.05, 0.10, 0.05]

# Intentionally messy — ETL will normalize these
TECHNICIANS_RAW = [
    "john.smith", "J. Smith", "john smith", "JOHN.SMITH",    # same person
    "maria.garcia", "Maria Garcia", "m.garcia",               # same person
    "dev.patel", "Dev Patel", "D. Patel",                    # same person
    "sarah.jones", "S.Jones", "sjones",                       # same person
    "mike.chen", "M. Chen", "mchen",                          # same person
    "lisa.brown", "Lisa B.", "l.brown",                       # same person
    "tom.wilson", "T. Wilson",                                 # same person
]

DEPARTMENTS = [
    "Finance", "HR", "IT", "Operations", "Sales",
    "Marketing", "Legal", "Engineering", "Executive", "Facilities"
]

ISSUE_TEMPLATES = {
    "Hardware":          ["Laptop won't turn on", "Monitor not displaying", "Keyboard not working",
                          "Mouse unresponsive", "Docking station issues", "Battery not charging"],
    "Software":          ["Application crash on launch", "Unable to install software",
                          "Blue screen of death", "Slow computer performance", "License expired",
                          "Software update failing"],
    "Network":           ["No internet access", "Slow network speeds", "Cannot connect to shared drive",
                          "WiFi dropping frequently", "Cannot reach internal servers"],
    "Access / Identity": ["Locked out of account", "Password reset request", "MFA not working",
                          "New user access request", "Permission denied on folder",
                          "Account disabled by policy"],
    "Email":             ["Cannot send email", "Email not syncing", "Outlook keeps crashing",
                          "Missing emails", "Shared mailbox access issue"],
    "Printing":          ["Printer offline", "Print jobs stuck in queue", "Paper jam",
                          "Cannot find network printer", "Poor print quality"],
    "VPN":               ["VPN not connecting", "VPN drops frequently", "Slow VPN speeds",
                          "MFA prompt not appearing for VPN", "VPN client error"],
    "Security":          ["Suspicious email received", "Possible malware detected",
                          "Unauthorized access attempt", "USB policy violation", "Phishing link clicked"],
    "Onboarding":        ["New hire laptop setup", "New hire account creation",
                          "Software installation for new hire", "Badge access request"],
    "Other":             ["General IT question", "Request for information", "IT policy question",
                          "Hardware disposal request"],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def random_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def resolution_hours(priority: str) -> float | None:
    """Simulate realistic resolution times; open/in-progress tickets have no resolution time."""
    sla_map = {
        "P1-Critical": (1, 4),
        "P2-High":     (4, 24),
        "P3-Medium":   (24, 72),
        "P4-Low":      (48, 168),
    }
    lo, hi = sla_map[priority]
    # Add realistic noise — some tickets breach SLA
    multiplier = np.random.lognormal(0, 0.5)
    return round(lo + (hi - lo) * random.random() * multiplier, 2)


def sla_target(priority: str) -> int:
    """Returns SLA target in hours by priority."""
    return {"P1-Critical": 4, "P2-High": 24, "P3-Medium": 72, "P4-Low": 168}[priority]


# ── Main Generation ───────────────────────────────────────────────────────────

def generate_tickets(n: int) -> pd.DataFrame:
    rows = []

    for i in range(1, n + 1):
        ticket_id  = f"TKT-{i:05d}"
        category   = random.choices(CATEGORIES, weights=[12,18,14,16,10,6,8,5,7,4])[0]
        priority   = random.choices(PRIORITIES, weights=PRIORITY_WEIGHTS)[0]
        status     = random.choices(STATUSES,   weights=STATUS_WEIGHTS)[0]
        tech       = random.choice(TECHNICIANS_RAW)
        dept       = random.choice(DEPARTMENTS)
        subject    = random.choice(ISSUE_TEMPLATES[category])
        created_at = random_date(START_DATE, END_DATE)

        # Resolution time — only resolved/closed tickets get one
        if status in ("Resolved", "Closed"):
            res_hours  = resolution_hours(priority)
            resolved_at = created_at + timedelta(hours=res_hours)
        else:
            res_hours   = None
            resolved_at = None

        # Introduce dirty data intentionally
        if random.random() < 0.03:
            dept = None          # ~3% null departments
        if random.random() < 0.02:
            tech = None          # ~2% unassigned tickets
        if random.random() < 0.01:
            priority = "URGENT"  # invalid priority value — ETL will normalize

        rows.append({
            "ticket_id":        ticket_id,
            "created_at":       created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "resolved_at":      resolved_at.strftime("%Y-%m-%d %H:%M:%S") if resolved_at else None,
            "status":           status,
            "priority":         priority,
            "category":         category,
            "subject":          subject,
            "technician":       tech,
            "department":       dept,
            "resolution_hours": res_hours,
            "sla_target_hours": sla_target(priority) if priority in sla_target.__doc__ else 72,
        })

    df = pd.DataFrame(rows)

    # Introduce ~1% duplicate rows to test dedup logic
    dupes = df.sample(frac=0.01, random_state=99)
    df = pd.concat([df, dupes], ignore_index=True)

    return df


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df = generate_tickets(NUM_TICKETS)
    out_path = os.path.join(OUTPUT_DIR, "tickets_raw.csv")
    df.to_csv(out_path, index=False)
    print(f"✅  Generated {len(df):,} rows → {out_path}")
    print(f"    Columns : {list(df.columns)}")
    print(f"    Date range : {df['created_at'].min()} → {df['created_at'].max()}")
