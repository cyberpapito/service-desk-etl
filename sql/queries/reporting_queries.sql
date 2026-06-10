-- =============================================================================
-- Service Desk Analytics — Reporting Queries
-- =============================================================================
-- Each query is self-contained with a comment block describing:
--   • Business question it answers
--   • Power BI visual it feeds
--   • Resume-ready skill it demonstrates
-- =============================================================================


-- =============================================================================
-- Q1: TICKET VOLUME BY MONTH
-- Business: How many tickets are opened each month?
-- Power BI: Line chart / Column chart on Executive Dashboard
-- Skills  : DATE functions, GROUP BY, ORDER BY, aliasing
-- =============================================================================
SELECT
    ft.created_year                          AS year,
    ft.created_month                         AS month_num,
    ft.created_month_name                    AS month,
    ft.created_quarter                       AS quarter,
    COUNT(ft.ticket_id)                      AS total_tickets,
    SUM(CASE WHEN ft.status IN ('Resolved','Closed') THEN 1 ELSE 0 END)
                                             AS resolved_tickets,
    SUM(CASE WHEN ft.status IN ('Open','In Progress','Pending') THEN 1 ELSE 0 END)
                                             AS open_tickets,
    ROUND(
        100.0 * SUM(CASE WHEN ft.status IN ('Resolved','Closed') THEN 1 ELSE 0 END)
        / COUNT(ft.ticket_id), 1
    )                                        AS resolution_rate_pct
FROM fact_tickets ft
GROUP BY
    ft.created_year,
    ft.created_month,
    ft.created_month_name,
    ft.created_quarter
ORDER BY
    ft.created_year,
    ft.created_month;


-- =============================================================================
-- Q2: TICKET VOLUME BY CATEGORY
-- Business: Which issue types generate the most work?
-- Power BI: Bar chart — Category Breakdown
-- Skills  : JOIN, GROUP BY, RANK window function
-- =============================================================================
SELECT
    dc.category_name                         AS category,
    COUNT(ft.ticket_id)                      AS total_tickets,
    ROUND(
        100.0 * COUNT(ft.ticket_id)
        / SUM(COUNT(ft.ticket_id)) OVER (), 1
    )                                        AS pct_of_total,
    ROUND(AVG(ft.resolution_hours), 2)       AS avg_resolution_hours,
    RANK() OVER (ORDER BY COUNT(ft.ticket_id) DESC)
                                             AS volume_rank
FROM fact_tickets ft
JOIN dim_category dc ON ft.category_key = dc.category_key
GROUP BY dc.category_name
ORDER BY total_tickets DESC;


-- =============================================================================
-- Q3: AVERAGE RESOLUTION TIME BY PRIORITY
-- Business: Are we resolving tickets faster for critical issues?
-- Power BI: KPI cards + grouped bar chart
-- Skills  : Conditional aggregation, ROUND, filtering on status
-- =============================================================================
SELECT
    dp.priority_label                        AS priority,
    dp.sla_hours                             AS sla_target_hours,
    COUNT(ft.ticket_id)                      AS total_tickets,
    COUNT(ft.resolution_hours)               AS resolved_tickets,
    ROUND(AVG(ft.resolution_hours), 2)       AS avg_resolution_hours,
    ROUND(MIN(ft.resolution_hours), 2)       AS min_resolution_hours,
    ROUND(MAX(ft.resolution_hours), 2)       AS max_resolution_hours,
    ROUND(
        100.0 * SUM(CASE WHEN ft.sla_met = 1 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(ft.resolution_hours), 0), 1
    )                                        AS sla_compliance_pct
FROM fact_tickets ft
JOIN dim_priority dp ON ft.priority_key = dp.priority_key
GROUP BY dp.priority_label, dp.sla_hours
ORDER BY dp.priority_key;


-- =============================================================================
-- Q4: SLA COMPLIANCE SUMMARY
-- Business: Are we meeting our SLA targets? (Executive-level KPI)
-- Power BI: Gauge chart, KPI card, compliance trend line
-- Skills  : CASE WHEN aggregation, percentage calculation, COALESCE
-- =============================================================================
SELECT
    COUNT(ft.ticket_id)                                      AS total_tickets,
    COUNT(ft.resolution_hours)                               AS resolved_tickets,
    SUM(CASE WHEN ft.sla_met = 1 THEN 1 ELSE 0 END)         AS sla_met_count,
    SUM(CASE WHEN ft.sla_met = 0 THEN 1 ELSE 0 END)         AS sla_breached_count,
    SUM(CASE WHEN ft.sla_met IS NULL THEN 1 ELSE 0 END)      AS sla_pending_count,
    ROUND(
        100.0 * SUM(CASE WHEN ft.sla_met = 1 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(ft.resolution_hours), 0), 1
    )                                                        AS overall_sla_compliance_pct
FROM fact_tickets ft;


-- =============================================================================
-- Q5: SLA COMPLIANCE BY MONTH (Trend)
-- Business: Is our SLA performance improving over time?
-- Power BI: Line chart with target reference line at 95%
-- =============================================================================
SELECT
    ft.created_year                                          AS year,
    ft.created_month                                         AS month_num,
    ft.created_month_name                                    AS month,
    COUNT(ft.resolution_hours)                               AS resolved_count,
    SUM(CASE WHEN ft.sla_met = 1 THEN 1 ELSE 0 END)         AS met_count,
    SUM(CASE WHEN ft.sla_met = 0 THEN 1 ELSE 0 END)         AS breached_count,
    ROUND(
        100.0 * SUM(CASE WHEN ft.sla_met = 1 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(ft.resolution_hours), 0), 1
    )                                                        AS compliance_pct,
    95.0                                                     AS target_pct
FROM fact_tickets ft
WHERE ft.resolution_hours IS NOT NULL
GROUP BY ft.created_year, ft.created_month, ft.created_month_name
ORDER BY ft.created_year, ft.created_month;


-- =============================================================================
-- Q6: TOP RECURRING ISSUES
-- Business: What are the most common ticket subjects? (Knowledge base candidates)
-- Power BI: Horizontal bar chart, word cloud data
-- Skills  : GROUP BY on text, LIMIT, window ranking
-- =============================================================================
SELECT
    ft.subject                               AS issue,
    dc.category_name                         AS category,
    COUNT(ft.ticket_id)                      AS occurrence_count,
    ROUND(AVG(ft.resolution_hours), 2)       AS avg_resolution_hours,
    ROUND(
        100.0 * COUNT(ft.ticket_id)
        / SUM(COUNT(ft.ticket_id)) OVER (), 1
    )                                        AS pct_of_total,
    RANK() OVER (ORDER BY COUNT(ft.ticket_id) DESC)
                                             AS frequency_rank
FROM fact_tickets ft
JOIN dim_category dc ON ft.category_key = dc.category_key
GROUP BY ft.subject, dc.category_name
ORDER BY occurrence_count DESC
LIMIT 20;


-- =============================================================================
-- Q7: TECHNICIAN WORKLOAD & PERFORMANCE
-- Business: How is work distributed? Who is our highest performer?
-- Power BI: Table visual + bar chart on Technician Dashboard
-- Skills  : Multi-metric aggregation, JOINs, conditional logic
-- =============================================================================
SELECT
    dt.technician_name                       AS technician,
    COUNT(ft.ticket_id)                      AS total_assigned,
    SUM(CASE WHEN ft.status IN ('Resolved','Closed') THEN 1 ELSE 0 END)
                                             AS resolved_count,
    SUM(CASE WHEN ft.status IN ('Open','In Progress','Pending') THEN 1 ELSE 0 END)
                                             AS open_count,
    ROUND(AVG(ft.resolution_hours), 2)       AS avg_resolution_hours,
    ROUND(
        100.0 * SUM(CASE WHEN ft.sla_met = 1 THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN ft.sla_met IS NOT NULL THEN 1 ELSE 0 END), 0), 1
    )                                        AS sla_compliance_pct,
    ROUND(
        100.0 * SUM(CASE WHEN ft.status IN ('Resolved','Closed') THEN 1 ELSE 0 END)
        / COUNT(ft.ticket_id), 1
    )                                        AS resolution_rate_pct,
    RANK() OVER (ORDER BY COUNT(ft.ticket_id) DESC)
                                             AS workload_rank
FROM fact_tickets ft
JOIN dim_technician dt ON ft.technician_key = dt.technician_key
WHERE dt.technician_name != 'Unassigned'
GROUP BY dt.technician_name
ORDER BY total_assigned DESC;


-- =============================================================================
-- Q8: DEPARTMENT TICKET TRENDS
-- Business: Which departments generate the most tickets? Identify power users.
-- Power BI: Treemap or stacked bar chart
-- =============================================================================
SELECT
    dd.department_name                       AS department,
    COUNT(ft.ticket_id)                      AS total_tickets,
    ROUND(AVG(ft.resolution_hours), 2)       AS avg_resolution_hours,
    SUM(CASE WHEN ft.sla_met = 0 THEN 1 ELSE 0 END)
                                             AS sla_breaches,
    ROUND(
        100.0 * COUNT(ft.ticket_id)
        / SUM(COUNT(ft.ticket_id)) OVER (), 1
    )                                        AS pct_of_total,
    RANK() OVER (ORDER BY COUNT(ft.ticket_id) DESC)
                                             AS volume_rank
FROM fact_tickets ft
JOIN dim_department dd ON ft.department_key = dd.department_key
GROUP BY dd.department_name
ORDER BY total_tickets DESC;


-- =============================================================================
-- Q9: OPEN TICKET AGING REPORT
-- Business: How old are our currently open tickets? Escalation risk assessment.
-- Power BI: Table with conditional formatting (red = overdue)
-- =============================================================================
SELECT
    ft.ticket_id,
    dt.technician_name                       AS technician,
    dd.department_name                       AS department,
    dc.category_name                         AS category,
    dp.priority_label                        AS priority,
    ft.subject,
    ft.status,
    ft.created_at,
    ft.age_hours,
    ft.age_bucket,
    dp.sla_hours                             AS sla_target_hours,
    CASE
        WHEN ft.age_hours > dp.sla_hours THEN 'SLA Breached'
        WHEN ft.age_hours > dp.sla_hours * 0.75 THEN 'At Risk'
        ELSE 'On Track'
    END                                      AS sla_status
FROM fact_tickets ft
JOIN dim_technician dt ON ft.technician_key = dt.technician_key
JOIN dim_department  dd ON ft.department_key = dd.department_key
JOIN dim_category    dc ON ft.category_key   = dc.category_key
JOIN dim_priority    dp ON ft.priority_key   = dp.priority_key
WHERE ft.status IN ('Open', 'In Progress', 'Pending')
ORDER BY ft.age_hours DESC;


-- =============================================================================
-- Q10: EXECUTIVE KPI SUMMARY (Single-row summary for KPI cards)
-- Business: One-glance health check for leadership
-- Power BI: KPI card visual row across top of Executive Dashboard
-- =============================================================================
SELECT
    COUNT(ft.ticket_id)                                      AS total_tickets_ytd,
    SUM(CASE WHEN ft.status IN ('Open','In Progress','Pending') THEN 1 ELSE 0 END)
                                                             AS currently_open,
    SUM(CASE WHEN ft.status IN ('Resolved','Closed') THEN 1 ELSE 0 END)
                                                             AS total_resolved,
    ROUND(AVG(ft.resolution_hours), 1)                       AS avg_resolution_hours,
    ROUND(
        100.0 * SUM(CASE WHEN ft.sla_met = 1 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(ft.resolution_hours), 0), 1
    )                                                        AS sla_compliance_pct,
    SUM(CASE WHEN ft.priority_key = 1 THEN 1 ELSE 0 END)    AS p1_critical_tickets,
    SUM(CASE WHEN ft.sla_met = 0 THEN 1 ELSE 0 END)         AS total_sla_breaches
FROM fact_tickets ft;
