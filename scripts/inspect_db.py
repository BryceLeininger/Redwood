import argparse
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="ryness.db")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()

    rid = cur.execute("select max(id) from reports").fetchone()[0]
    print("latest_report_id", rid)

    oak_any = cur.execute(
        "select max(report_id) from city_codes where city_name like 'Oakland%'"
    ).fetchone()[0]
    print("most_recent_report_with_oakland", oak_any)

    if oak_any is not None:
        oak_any_rows = cur.execute(
            "select city_code, city_name from city_codes where report_id=? and city_name like 'Oakland%'",
            (oak_any,),
        ).fetchall()
        print("oakland_rows_in_city_codes_for_that_report", oak_any_rows)

    oak = cur.execute(
        "select city_code, city_name from city_codes where report_id=? and city_name like 'Oakland%'",
        (rid,),
    ).fetchall()
    print("oakland_rows_in_city_codes", oak)

    city_codes_count = cur.execute(
        "select count(*) from city_codes where report_id=?", (rid,)
    ).fetchone()[0]
    print("city_codes_count", city_codes_count)

    ps_codes = cur.execute(
        "select city_code, count(*) c from project_stats where report_id=? group by city_code order by c desc limit 20",
        (rid,),
    ).fetchall()
    print("top_project_city_codes", ps_codes)

    for (code, _name) in oak:
        n = cur.execute(
            "select count(*) from project_stats where report_id=? and upper(city_code)=upper(?)",
            (rid, code),
        ).fetchone()[0]
        print("projects_with_oakland_code_casefold", code, n)
        sample = cur.execute(
            "select development_name, city_code from project_stats where report_id=? and upper(city_code)=upper(?) limit 10",
            (rid, code),
        ).fetchall()
        print("sample_projects", sample)


if __name__ == "__main__":
    main()
