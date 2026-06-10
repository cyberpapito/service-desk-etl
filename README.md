# Service Desk Analytics ETL Pipeline

An end-to-end ETL pipeline built to demonstrate practical data engineering skills — from raw messy CSV data through Python transformation into a star-schema SQLite database, with a Power BI dashboard on top for business reporting.

I built this to challenge myself on the upstream side of data: ETL design, schema modeling, pipeline architecture, skills I don't use in my current IT role but need to break into data engineering. The service desk domain was a natural fit since it's territory I know well, which let me focus on learning the engineering without getting lost in an unfamiliar problem space.

---

## What it does

The pipeline ingests raw service desk ticket data, cleans it, and loads it into a structured database that Power BI can query for executive reporting.

The raw data is intentionally messy — duplicate tickets, null departments, technician names entered seven different ways across different systems, invalid priority values. The ETL pipeline handles all of it systematically, which is closer to what real-world data pipelines actually deal with.

**Extract** — reads raw CSV ticket files from `data/raw/`

**Transform** — runs eight cleaning and enrichment steps:
- Removes duplicate rows (ticket_id must be unique)
- Fills null technicians → "Unassigned", null departments → "Unknown"
- Normalizes technician name variants — `john.smith`, `J. Smith`, `JOHN.SMITH` all resolve to `John Smith`
- Normalizes priority values — `URGENT`, `urgent`, `1` all resolve to `P1-Critical`
- Calculates SLA compliance — resolution time vs. target by priority
- Calculates ticket aging and buckets (< 4h, 4–24h, 1–3 days, etc.)
- Adds date dimensions (year, month, quarter, weekday) for Power BI time intelligence

**Load** — writes to a five-table SQLite star schema using `INSERT OR REPLACE` so the pipeline is safe to re-run

---

## Dashboard

Three-page Power BI dashboard built on top of the processed data.

**Executive Dashboard** — KPI cards (total tickets, open tickets, avg resolution time, SLA compliance %), ticket volume trend by month, ticket breakdown by category

**Technician Performance** — workload distribution across technicians, performance table with avg resolution hours and SLA compliance per technician

**Department & SLA** — ticket volume by department, SLA compliance trend across the year

---

## Stack

- Python 3.11 / Pandas / NumPy
- SQLite
- SQL (schema design, indexing, 10 reporting queries)
- Power BI Desktop (DAX measures, cross-filtering)
- Git / GitHub

---

## Getting started

```bash
git clone https://github.com/cyberpapito/service-desk-etl.git
cd service-desk-etl
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Generate the sample data:
```bash
python etl/generate_data.py
```

Run the pipeline:
```bash
python etl/pipeline.py
```

The database lands at `data/processed/service_desk.db`. Open `ServiceDeskAnalytics.pbix` in Power BI Desktop or connect directly to `data/processed/tickets_processed.csv`.

---

## Database schema

Star schema with one fact table and four dimensions.

```
                    dim_technician
                          │
dim_category ──── fact_tickets ──── dim_department
                          │
                    dim_priority
                    (stores SLA targets)
```

`fact_tickets` holds one row per ticket with foreign keys into each dimension and numeric measures for resolution time, SLA compliance, and ticket aging. Date dimensions are denormalized onto the fact table for Power BI performance.

---

## Project structure

```
service-desk-etl/
├── etl/
│   ├── generate_data.py     # synthetic data generator
│   ├── transform.py         # all cleaning and enrichment logic
│   ├── load.py              # schema creation and data loading
│   └── pipeline.py          # main ETL orchestrator
├── sql/
│   ├── schema/create_tables.sql
│   └── queries/reporting_queries.sql   # 10 BI queries
├── docs/
│   └── powerbi_setup.md
├── data/
│   ├── raw/                 # source files (gitignored)
│   ├── processed/           # database + clean CSV (gitignored)
│   └── archive/             # timestamped raw file copies
├── ServiceDeskAnalytics.pbix
└── requirements.txt
```

---

## SQL reporting queries

Ten queries written against the star schema covering ticket volume trends, SLA compliance by priority and month, technician workload and performance, department analysis, top recurring issues, and an open ticket aging report with escalation risk flags.

---

## What I'd add with more time

- PostgreSQL swap — the schema is production-ready, SQLite is just for portability
- Airflow DAG for scheduled daily runs
- ServiceNow or Jira API as the extract source instead of CSV
- pytest suite for the transform functions
- Incremental loads instead of full reload on each run
- Email alert when SLA compliance drops below threshold

---

*Part of a portfolio built during a transition from IT systems administration into data engineering and BI roles.*
