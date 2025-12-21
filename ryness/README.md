# Ryness Report Ingest

This parser ingests weekly Ryness Report PDFs into a SQLite database.

## Setup

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Ingest

```bash
python -m ryness.ingest "092825 NorCal Ryness Report.pdf" --db ryness.db
```

## Natural language query (OpenAI)

Set your API key:

```bash
setx OPENAI_API_KEY "your-key"
```

Ask a question:

```bash
python -m ryness.query "Top 10 projects by weekly sales" --db ryness.db
```

Add a short GPT summary:

```bash
python -m ryness.query "How did Alameda compare to Contra Costa this week?" --db ryness.db --analysis
```

## Batch ingest a folder

```bash
python -m ryness.batch_ingest "C:\path\to\RynessReportsPDFs" --db ryness.db
```

## Tables

- `reports`
- `county_summary`
- `weekly_metrics`
- `yearly_comparison`
- `project_stats`
- `project_totals`
- `mls_survey`

## Example SQL

```sql
-- Top 10 projects by weekly sales
SELECT development_name, wk_sales, county_group
FROM project_stats
ORDER BY wk_sales DESC
LIMIT 10;
```
