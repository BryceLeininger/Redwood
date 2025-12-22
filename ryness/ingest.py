import argparse
import datetime as dt
import pathlib
import re
import sqlite3

import pdfplumber


SCHEMA_PATH = pathlib.Path(__file__).with_name("schema.sql")


def init_db(conn):
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def to_int(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "na", "n/a"}:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def to_float(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "na", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_week_info(text):
    week_num = None
    week_ending = None
    region = None
    m = re.search(r"Week\s+(\d+)\s+Ending:\s*(.+)", text)
    if m:
        week_num = to_int(m.group(1))
        week_ending = m.group(2).strip()
    for line in text.splitlines():
        if line.strip() == "Bay Area":
            region = "Bay Area"
            break
    return week_num, week_ending, region


def parse_county_summary(text):
    rows = []
    line_pattern = re.compile(
        r"^(?P<county>.+?)\s+"
        r"(?P<projects>\d+)\s+"
        r"(?P<traffic>\d+)\s+"
        r"(?P<sales>\d+)\s+"
        r"(?P<cancels>\d+)\s+"
        r"(?P<net_sales>\d+)\s+"
        r"(?P<avg_sales>\d+\.\d+)\s+"
        r"(?P<ytd_avg>\d+\.\d+)\s+"
        r"(?P<ytd_diff>-?\d+%)\s+"
        r"(?P<prev13_avg>\d+\.\d+)\s+"
        r"(?P<prev13_diff>-?\d+%)$"
    )
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = line_pattern.match(line)
        if not m:
            continue
        rows.append(
            {
                "county_group": m.group("county"),
                "projects": to_int(m.group("projects")),
                "traffic": to_int(m.group("traffic")),
                "sales": to_int(m.group("sales")),
                "cancels": to_int(m.group("cancels")),
                "net_sales": to_int(m.group("net_sales")),
                "avg_sales": to_float(m.group("avg_sales")),
                "ytd_avg": to_float(m.group("ytd_avg")),
                "ytd_diff": m.group("ytd_diff"),
                "prev13_avg": to_float(m.group("prev13_avg")),
                "prev13_diff": m.group("prev13_diff"),
            }
        )
    return rows


def parse_weekly_metrics(text):
    rows = []
    current_week = re.search(
        r"Current Week Totals Traffic : Sales (\d+)\s*:\s*(\d+)\s+"
        r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+"
        r"(\d+\.\d+)\s+(\d+\.\d+)\s+(-?\d+%)\s+(\d+\.\d+)\s+(-?\d+%)",
        text,
    )
    if current_week:
        rows.append(
            {
                "label": "current_week_totals",
                "traffic_to_sales": f"{current_week.group(1)} : {current_week.group(2)}",
                "projects": to_int(current_week.group(3)),
                "traffic": to_int(current_week.group(4)),
                "sales": to_int(current_week.group(5)),
                "cancels": to_int(current_week.group(6)),
                "net_sales": to_int(current_week.group(7)),
                "avg_sales": to_float(current_week.group(8)),
                "ytd_avg": to_float(current_week.group(9)),
                "ytd_diff": current_week.group(10),
                "prev13_avg": to_float(current_week.group(11)),
                "prev13_diff": current_week.group(12),
            }
        )

    year_ago = re.search(
        r"Year Ago - (\d{2}/\d{2}/\d{4}) Traffic : Sales (\d+)\s*:\s*(\d+)\s+"
        r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+"
        r"(\d+\.\d+)\s+(\d+\.\d+)\s+(-?\d+%)\s+(\d+\.\d+)\s+(-?\d+%)",
        text,
    )
    if year_ago:
        rows.append(
            {
                "label": "year_ago",
                "as_of_date": year_ago.group(1),
                "traffic_to_sales": f"{year_ago.group(2)} : {year_ago.group(3)}",
                "projects": to_int(year_ago.group(4)),
                "traffic": to_int(year_ago.group(5)),
                "sales": to_int(year_ago.group(6)),
                "cancels": to_int(year_ago.group(7)),
                "net_sales": to_int(year_ago.group(8)),
                "avg_sales": to_float(year_ago.group(9)),
                "ytd_avg": to_float(year_ago.group(10)),
                "ytd_diff": year_ago.group(11),
                "prev13_avg": to_float(year_ago.group(12)),
                "prev13_diff": year_ago.group(13),
            }
        )

    per_project = re.search(
        r"Per Project Average\s+(\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)",
        text,
    )
    if per_project:
        rows.append(
            {
                "label": "per_project_average",
                "traffic": to_int(per_project.group(1)),
                "sales": to_float(per_project.group(2)),
                "cancels": to_float(per_project.group(3)),
                "net_sales": to_float(per_project.group(4)),
            }
        )

    percent_change = re.search(
        r"% Change\s+(-?\d+%)\s+(-?\d+%)\s+(-?\d+%)\s+(-?\d+%)\s+(-?\d+%)\s+(-?\d+%)\s+(-?\d+%)\s+(-?\d+%)",
        text,
    )
    if percent_change:
        rows.append(
            {
                "label": "percent_change",
                "projects": percent_change.group(1),
                "traffic": percent_change.group(2),
                "sales": percent_change.group(3),
                "cancels": percent_change.group(4),
                "net_sales": percent_change.group(5),
                "avg_sales": percent_change.group(6),
                "ytd_avg": percent_change.group(7),
                "prev13_avg": percent_change.group(8),
            }
        )

    return rows


def parse_yearly_comparison(page):
    tables = page.extract_tables() or []
    if len(tables) < 2:
        return []
    table = tables[1]
    rows = []
    for row in table[1:]:
        if not row or not row[0]:
            continue
        nums = re.findall(r"\d+\.\d+|\d+", str(row[0]))
        if len(nums) < 5:
            continue
        year = to_int(nums[0])
        avg_weekly_projects = to_float(nums[1])
        avg_weekly_traffic = to_float(nums[2])
        avg_weekly_sales = to_float(nums[3])
        avg_weekly_cancels = to_float(nums[4])
        avg_project_sales = to_float(row[6]) if len(row) > 6 else None
        year_end_avg_proj_sales = to_float(row[7]) if len(row) > 7 else None
        if year is None:
            continue
        rows.append(
            {
                "year": year,
                "avg_weekly_projects": avg_weekly_projects,
                "avg_weekly_traffic": avg_weekly_traffic,
                "avg_weekly_sales": avg_weekly_sales,
                "avg_weekly_cancels": avg_weekly_cancels,
                "avg_project_sales": avg_project_sales,
                "year_end_avg_proj_sales": year_end_avg_proj_sales,
            }
        )
    return rows


def group_words_by_line(words, y_tol=2):
    lines = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if not lines or abs(word["top"] - lines[-1]["top"]) > y_tol:
            lines.append({"top": word["top"], "words": [word]})
        else:
            lines[-1]["words"].append(word)
    return lines


def parse_city_codes_from_text(text):
    tails = []
    for line in (text or "").splitlines():
        if "City Codes:" not in line:
            continue
        tail = line.split("City Codes:", 1)[1].strip()
        if tail:
            tails.append(tail)

    if not tails:
        return []

    blob = re.sub(r"\s+", " ", " ".join(tails)).strip()
    rows = []
    for m in re.finditer(r"\b([A-Za-z]{1,4})\s*=\s*([^,]+)", blob):
        code = m.group(1).strip().upper()
        name = m.group(2).strip()
        if not code or not name:
            continue
        rows.append({"city_code": code, "city_name": name})
    return rows


def normalize_city_code(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    m = re.match(r"^[A-Za-z]{1,4}", text)
    if m:
        return m.group(0).upper()
    return text.upper()


PROJECT_COLS = [
    ("development_name", 20),
    ("developer", 150),
    ("city_code", 230),
    ("notes", 280),
    ("product_type", 330),
    ("units", 370),
    ("new_release", 400),
    ("released_remaining", 418),
    ("traffic", 440),
    ("wk_sales", 465),
    ("wk_cancels", 488),
    ("sold_to_date", 508),
    ("sold_ytd", 528),
    ("avg_sales_week", 548),
    ("avg_sales_ytd", 572),
]


def assign_project_columns(words):
    row = {name: [] for name, _ in PROJECT_COLS}
    for word in words:
        x = (word["x0"] + word["x1"]) / 2.0
        idx = None
        for i, (_, x0) in enumerate(PROJECT_COLS):
            x1 = PROJECT_COLS[i + 1][1] if i + 1 < len(PROJECT_COLS) else 10000
            if x0 <= x < x1:
                idx = i
                break
        if idx is None:
            continue
        row[PROJECT_COLS[idx][0]].append(word["text"])
    return {k: " ".join(v).strip() if v else "" for k, v in row.items()}


def parse_project_tables(pdf):
    rows = []
    totals_rows = []
    city_code_rows = []
    for page in pdf.pages:
        text = page.extract_text() or ""

        if "City Codes:" in text:
            city_code_rows.extend(parse_city_codes_from_text(text))

        if "Development Name Developer City Code Notes Type" not in text:
            continue
        county_group = None
        projects_participating = None
        m = re.search(r"^(.+?)\s+\|\s+(.+)$", text, flags=re.MULTILINE)
        if m:
            county_group = m.group(1).strip()
        m = re.search(r"Projects Participating:\s*(\d+)", text)
        if m:
            projects_participating = to_int(m.group(1))

        words = page.extract_words()
        header_words = [w for w in words if w["text"] == "Development"]
        data_top = max(w["top"] for w in header_words) + 18 if header_words else 100
        data_words = [w for w in words if w["top"] >= data_top]
        for line in group_words_by_line(data_words):
            line_words = sorted(line["words"], key=lambda w: w["x0"])
            line_text = " ".join(w["text"] for w in line_words).strip()
            if not line_text:
                continue
            if line_text.startswith("TOTALS:") or line_text.startswith("GRAND TOTALS:"):
                totals_rows.append(
                    {
                        "county_group": county_group,
                    "no_reporting": to_int(re.search(r"No\. Reporting:\s*(\d+)", line_text).group(1))
                    if re.search(r"No\. Reporting:\s*(\d+)", line_text)
                    else None,
                    "avg_sales": to_float(re.search(r"Avg\. Sales:\s*([\d\.]+)", line_text).group(1))
                    if re.search(r"Avg\. Sales:\s*([\d\.]+)", line_text)
                    else None,
                    "traffic_to_sales": re.search(r"Traffic to Sales:\s*([0-9\s:]+)", line_text).group(1).strip()
                    if re.search(r"Traffic to Sales:\s*([0-9\s:]+)", line_text)
                    else None,
                    "net_sales": to_int(re.search(r"Net:\s*(\d+)", line_text).group(1))
                    if re.search(r"Net:\s*(\d+)", line_text)
                    else None,
                    }
                )
                continue
            if line_text.startswith("City Codes:") or line_text.startswith("Project Types:"):
                continue
            row = assign_project_columns(line_words)
            if not row["development_name"]:
                continue
            rows.append(
                {
                    "county_group": county_group,
                    "projects_participating": projects_participating,
                    "development_name": row["development_name"],
                    "developer": row["developer"],
                    "city_code": normalize_city_code(row["city_code"]),
                    "notes": row["notes"],
                    "product_type": row["product_type"],
                    "units": to_int(row["units"]),
                    "new_release": to_int(row["new_release"]),
                    "released_remaining": to_int(row["released_remaining"]),
                    "traffic": to_int(row["traffic"]),
                    "wk_sales": to_int(row["wk_sales"]),
                    "wk_cancels": to_int(row["wk_cancels"]),
                    "sold_to_date": to_int(row["sold_to_date"]),
                    "sold_ytd": to_int(row["sold_ytd"]),
                    "avg_sales_week": to_float(row["avg_sales_week"]),
                    "avg_sales_ytd": to_float(row["avg_sales_ytd"]),
                }
            )
    dedup = {}
    for r in city_code_rows:
        key = r["city_code"]
        if key and key not in dedup:
            dedup[key] = r
    return rows, totals_rows, list(dedup.values())


def parse_mls_surveys(pdf):
    rows = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "Monthly MLS Survey" not in text:
            continue
        market_name = None
        for line in text.splitlines():
            if "Monthly MLS Survey" in line:
                market_name = line.strip()
                break
        if not market_name:
            market_name = "Unknown Market"
        tables = page.extract_tables() or []
        for table in tables:
            if not table:
                continue
            for row in table:
                if not row or not row[0]:
                    continue
                month = str(row[0]).strip()
                if not re.fullmatch(r"[A-Za-z]{3}-\d{2}", month):
                    continue
                rows.append(
                    {
                        "market_name": market_name,
                        "month": month,
                        "active": to_int(row[1]),
                        "active_dom": to_int(row[2]),
                        "pending": to_int(row[3]),
                        "pending_dom": to_int(row[4]),
                        "closed": to_int(row[5]),
                        "avg_price": to_int(row[6]),
                    }
                )
    return rows


def ingest(pdf_path, db_path):
    pdf_path = pathlib.Path(pdf_path)
    db_path = pathlib.Path(db_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    with pdfplumber.open(str(pdf_path)) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        week_num, week_ending, region = parse_week_info(first_text)

        conn = sqlite3.connect(str(db_path))
        init_db(conn)

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reports (filename, report_week_ending, report_week_num, region, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                pdf_path.name,
                week_ending,
                week_num,
                region,
                dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            ),
        )
        report_id = cur.lastrowid

        for row in parse_county_summary(first_text):
            cur.execute(
                """
                INSERT INTO county_summary (
                    report_id, county_group, projects, traffic, sales, cancels, net_sales,
                    avg_sales, ytd_avg, ytd_diff, prev13_avg, prev13_diff
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    row["county_group"],
                    row["projects"],
                    row["traffic"],
                    row["sales"],
                    row["cancels"],
                    row["net_sales"],
                    row["avg_sales"],
                    row["ytd_avg"],
                    row["ytd_diff"],
                    row["prev13_avg"],
                    row["prev13_diff"],
                ),
            )

        for row in parse_weekly_metrics(first_text):
            cur.execute(
                """
                INSERT INTO weekly_metrics (
                    report_id, label, as_of_date, traffic_to_sales, projects, traffic, sales, cancels,
                    net_sales, avg_sales, ytd_avg, ytd_diff, prev13_avg, prev13_diff
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    row.get("label"),
                    row.get("as_of_date"),
                    row.get("traffic_to_sales"),
                    row.get("projects"),
                    row.get("traffic"),
                    row.get("sales"),
                    row.get("cancels"),
                    row.get("net_sales"),
                    row.get("avg_sales"),
                    row.get("ytd_avg"),
                    row.get("ytd_diff"),
                    row.get("prev13_avg"),
                    row.get("prev13_diff"),
                ),
            )

        for row in parse_yearly_comparison(pdf.pages[0]):
            cur.execute(
                """
                INSERT INTO yearly_comparison (
                    report_id, year, avg_weekly_projects, avg_weekly_traffic, avg_weekly_sales,
                    avg_weekly_cancels, avg_project_sales, year_end_avg_proj_sales
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    row["year"],
                    row["avg_weekly_projects"],
                    row["avg_weekly_traffic"],
                    row["avg_weekly_sales"],
                    row["avg_weekly_cancels"],
                    row["avg_project_sales"],
                    row["year_end_avg_proj_sales"],
                ),
            )

        project_rows, totals_rows, city_code_rows = parse_project_tables(pdf)
        for row in project_rows:
            cur.execute(
                """
                INSERT INTO project_stats (
                    report_id, county_group, projects_participating, development_name, developer,
                    city_code, notes, product_type, units, new_release, released_remaining, traffic,
                    wk_sales, wk_cancels, sold_to_date, sold_ytd, avg_sales_week, avg_sales_ytd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    row["county_group"],
                    row["projects_participating"],
                    row["development_name"],
                    row["developer"],
                    row["city_code"],
                    row["notes"],
                    row["product_type"],
                    row["units"],
                    row["new_release"],
                    row["released_remaining"],
                    row["traffic"],
                    row["wk_sales"],
                    row["wk_cancels"],
                    row["sold_to_date"],
                    row["sold_ytd"],
                    row["avg_sales_week"],
                    row["avg_sales_ytd"],
                ),
            )

        for row in totals_rows:
            cur.execute(
                """
                INSERT INTO project_totals (
                    report_id, county_group, no_reporting, avg_sales, traffic_to_sales, net_sales
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    row.get("county_group"),
                    row.get("no_reporting"),
                    row.get("avg_sales"),
                    row.get("traffic_to_sales"),
                    row.get("net_sales"),
                ),
            )

        for row in city_code_rows:
            cur.execute(
                """
                INSERT OR IGNORE INTO city_codes (report_id, city_code, city_name)
                VALUES (?, ?, ?)
                """,
                (
                    report_id,
                    row.get("city_code"),
                    row.get("city_name"),
                ),
            )

        for row in parse_mls_surveys(pdf):
            cur.execute(
                """
                INSERT INTO mls_survey (
                    report_id, market_name, month, active, active_dom, pending, pending_dom, closed, avg_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    row["market_name"],
                    row["month"],
                    row["active"],
                    row["active_dom"],
                    row["pending"],
                    row["pending_dom"],
                    row["closed"],
                    row["avg_price"],
                ),
            )

        conn.commit()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest a Ryness Report PDF into SQLite.")
    parser.add_argument("pdf", help="Path to the Ryness Report PDF.")
    parser.add_argument("--db", default="ryness.db", help="SQLite database path.")
    args = parser.parse_args()
    ingest(args.pdf, args.db)


if __name__ == "__main__":
    main()
