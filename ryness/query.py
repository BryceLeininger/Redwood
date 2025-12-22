import argparse
import os
import re
import sqlite3

from openai import OpenAI


def load_api_key():
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        return env_key

    candidates = [
        pathlib.Path("ryness/.openai_key"),
        pathlib.Path(".openai_key"),
        pathlib.Path.home() / ".ryness_openai_key",
    ]
    for path in candidates:
        if path.exists():
            key = path.read_text(encoding="utf-8").strip()
            if key:
                return key
    return None


def load_schema(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    lines = []
    for (name,) in rows:
        cols = conn.execute(f"PRAGMA table_info({name})").fetchall()
        col_defs = ", ".join(f"{col[1]} {col[2]}" for col in cols)
        lines.append(f"{name}({col_defs})")
    return "\n".join(lines)


def strip_sql(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def ensure_select(sql):
    sql = strip_sql(sql)
    if not re.match(r"(?is)^select\\b", sql):
        raise ValueError("Model did not return a SELECT statement.")
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("Model returned multiple statements.")
    return sql.rstrip(";")


def maybe_add_limit(sql, limit):
    if limit is None:
        return sql
    if re.search(r"\\blimit\\b", sql, flags=re.I):
        return sql
    return f"{sql} LIMIT {limit}"


def call_openai(model, schema, question):
    api_key = load_api_key()
    if not api_key:
        raise EnvironmentError(
            "OpenAI API key not found. Set OPENAI_API_KEY or create ryness/.openai_key."
        )
    client = OpenAI(api_key=api_key)

    system = (
        "You are a careful SQL generator for SQLite. "
        "Return only a single SELECT statement and nothing else. "
        "No comments, no code fences, no markdown."
    )
    user = f"Schema:\\n{schema}\\n\\nQuestion:\\n{question}"
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
    )
    return resp.choices[0].message.content or ""


def render_rows(rows):
    if not rows:
        return "(no rows)"
    headers = rows[0].keys()
    out = ["\\t".join(headers)]
    for row in rows:
        out.append("\\t".join("" if v is None else str(v) for v in row))
    return "\\n".join(out)


def analyze_results(model, question, rows):
    api_key = load_api_key()
    if not api_key:
        raise EnvironmentError(
            "OpenAI API key not found. Set OPENAI_API_KEY or create ryness/.openai_key."
        )
    client = OpenAI(api_key=api_key)
    preview = rows[:50]
    system = "You summarize SQL results for real estate reporting. Keep it concise."
    user = f"Question: {question}\\nRows: {preview}"
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


def main():
    parser = argparse.ArgumentParser(description="Query the Ryness SQLite DB using natural language.")
    parser.add_argument("question", help="Natural language question to ask.")
    parser.add_argument("--db", default="ryness.db", help="SQLite database path.")
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model name.")
    parser.add_argument("--limit", type=int, default=200, help="Row limit when SQL has none.")
    parser.add_argument("--analysis", action="store_true", help="Ask GPT to summarize results.")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    schema = load_schema(conn)
    sql = ensure_select(call_openai(args.model, schema, args.question))
    sql = maybe_add_limit(sql, args.limit)

    rows = conn.execute(sql).fetchall()
    print("SQL:")
    print(sql)
    print("")
    print("RESULTS:")
    print(render_rows(rows))

    if args.analysis:
        print("")
        print("ANALYSIS:")
        print(analyze_results(args.model, args.question, rows))


if __name__ == "__main__":
    main()
