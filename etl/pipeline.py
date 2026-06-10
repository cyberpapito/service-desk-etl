"""
pipeline.py
-----------
Main ETL pipeline entry point.

Orchestrates the full Extract → Transform → Load workflow.
Run this file to process all raw CSVs and populate the database.

Usage:
    python etl/pipeline.py
    python etl/pipeline.py --input data/raw/tickets_raw.csv
    python etl/pipeline.py --db data/processed/service_desk.db
"""

import argparse
import logging
import os
import shutil
import sys
from datetime import datetime
import pandas as pd

# Ensure etl package is importable when running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etl.transform import run_transforms
from etl.load import run_load, DB_PATH

# ── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join("data", "processed", "etl.log"), mode="a"),
    ],
)
logger = logging.getLogger(__name__)


# ── Extract ───────────────────────────────────────────────────────────────────

def extract(input_path: str) -> pd.DataFrame:
    """
    ETL Phase: EXTRACT
    Read raw CSV ticket file into a DataFrame.
    Logs shape and column names for observability.
    """
    logger.info(f"EXTRACT: Reading {input_path}")
    df = pd.read_csv(input_path, dtype=str)   # read all as str; transform handles casting
    logger.info(f"  ✓ Loaded {len(df):,} rows × {len(df.columns)} columns")
    logger.info(f"  Columns: {list(df.columns)}")
    return df


# ── Archive ───────────────────────────────────────────────────────────────────

def archive_raw_file(input_path: str):
    """
    Move processed raw files to data/archive/ with a timestamp suffix.
    This is a production best practice — raw files are never deleted,
    only moved, so you can always replay the pipeline from source.
    """
    archive_dir = os.path.join("data", "archive")
    os.makedirs(archive_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = os.path.basename(input_path)
    dest      = os.path.join(archive_dir, f"{timestamp}_{filename}")
    shutil.copy2(input_path, dest)
    logger.info(f"  ✓ Archived raw file → {dest}")


# ── Pipeline Orchestrator ─────────────────────────────────────────────────────

def run_pipeline(input_path: str, db_path: str, archive: bool = True):
    """
    Full ETL pipeline: Extract → Transform → Load

    Parameters
    ----------
    input_path : path to raw CSV file
    db_path    : path to SQLite database
    archive    : if True, copy raw file to data/archive after processing
    """
    start = datetime.now()
    logger.info("=" * 60)
    logger.info("SERVICE DESK ETL PIPELINE — START")
    logger.info(f"Input : {input_path}")
    logger.info(f"DB    : {db_path}")
    logger.info("=" * 60)

    # Ensure output directories exist
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # ── EXTRACT ──
    raw_df = extract(input_path)

    # ── TRANSFORM ──
    logger.info("TRANSFORM: Running transformation steps...")
    transformed_df = run_transforms(raw_df)

    # Save processed CSV for inspection / Power BI direct connection option
    processed_csv = os.path.join("data", "processed", "tickets_processed.csv")
    transformed_df.to_csv(processed_csv, index=False)
    logger.info(f"  ✓ Processed CSV saved → {processed_csv}")

    # ── LOAD ──
    logger.info("LOAD: Writing to database...")
    run_load(transformed_df, db_path=db_path)

    # ── ARCHIVE ──
    if archive:
        archive_raw_file(input_path)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info("=" * 60)
    logger.info(f"PIPELINE COMPLETE  ({elapsed:.1f}s)")
    logger.info(f"Database : {db_path}")
    logger.info(f"Rows     : {len(transformed_df):,}")
    logger.info("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Service Desk ETL Pipeline")
    parser.add_argument(
        "--input", default=os.path.join("data", "raw", "tickets_raw.csv"),
        help="Path to raw CSV input file"
    )
    parser.add_argument(
        "--db", default=DB_PATH,
        help="Path to SQLite database output"
    )
    parser.add_argument(
        "--no-archive", action="store_true",
        help="Skip archiving the raw input file"
    )
    args = parser.parse_args()

    run_pipeline(
        input_path=args.input,
        db_path=args.db,
        archive=not args.no_archive,
    )
