PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL,
  report_week_ending TEXT,
  report_week_num INTEGER,
  region TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS county_summary (
  report_id INTEGER NOT NULL REFERENCES reports(id),
  county_group TEXT NOT NULL,
  projects INTEGER,
  traffic INTEGER,
  sales INTEGER,
  cancels INTEGER,
  net_sales INTEGER,
  avg_sales REAL,
  ytd_avg REAL,
  ytd_diff TEXT,
  prev13_avg REAL,
  prev13_diff TEXT
);

CREATE TABLE IF NOT EXISTS weekly_metrics (
  report_id INTEGER NOT NULL REFERENCES reports(id),
  label TEXT NOT NULL,
  as_of_date TEXT,
  traffic_to_sales TEXT,
  projects INTEGER,
  traffic INTEGER,
  sales REAL,
  cancels REAL,
  net_sales REAL,
  avg_sales REAL,
  ytd_avg REAL,
  ytd_diff TEXT,
  prev13_avg REAL,
  prev13_diff TEXT
);

CREATE TABLE IF NOT EXISTS yearly_comparison (
  report_id INTEGER NOT NULL REFERENCES reports(id),
  year INTEGER NOT NULL,
  avg_weekly_projects REAL,
  avg_weekly_traffic REAL,
  avg_weekly_sales REAL,
  avg_weekly_cancels REAL,
  avg_project_sales REAL,
  year_end_avg_proj_sales REAL
);

CREATE TABLE IF NOT EXISTS project_stats (
  report_id INTEGER NOT NULL REFERENCES reports(id),
  county_group TEXT,
  projects_participating INTEGER,
  development_name TEXT,
  developer TEXT,
  city_code TEXT,
  notes TEXT,
  product_type TEXT,
  units INTEGER,
  new_release INTEGER,
  released_remaining INTEGER,
  traffic INTEGER,
  wk_sales INTEGER,
  wk_cancels INTEGER,
  sold_to_date INTEGER,
  sold_ytd INTEGER,
  avg_sales_week REAL,
  avg_sales_ytd REAL
);

CREATE TABLE IF NOT EXISTS project_totals (
  report_id INTEGER NOT NULL REFERENCES reports(id),
  county_group TEXT,
  no_reporting INTEGER,
  avg_sales REAL,
  traffic_to_sales TEXT,
  net_sales INTEGER
);

CREATE TABLE IF NOT EXISTS mls_survey (
  report_id INTEGER NOT NULL REFERENCES reports(id),
  market_name TEXT NOT NULL,
  month TEXT NOT NULL,
  active INTEGER,
  active_dom INTEGER,
  pending INTEGER,
  pending_dom INTEGER,
  closed INTEGER,
  avg_price INTEGER
);

CREATE TABLE IF NOT EXISTS city_codes (
  report_id INTEGER NOT NULL REFERENCES reports(id),
  city_code TEXT NOT NULL,
  city_name TEXT NOT NULL,
  PRIMARY KEY (report_id, city_code)
);

CREATE VIEW IF NOT EXISTS project_stats_with_city AS
SELECT
  ps.report_id,
  ps.county_group,
  ps.projects_participating,
  ps.development_name,
  ps.developer,
  ps.city_code,
  cc.city_name,
  ps.notes,
  ps.product_type,
  ps.units,
  ps.new_release,
  ps.released_remaining,
  ps.traffic,
  ps.wk_sales,
  ps.wk_cancels,
  ps.sold_to_date,
  ps.sold_ytd,
  ps.avg_sales_week,
  ps.avg_sales_ytd
FROM project_stats ps
LEFT JOIN city_codes cc
  ON cc.report_id = ps.report_id
 AND cc.city_code = ps.city_code;
