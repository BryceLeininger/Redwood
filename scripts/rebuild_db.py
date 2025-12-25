import argparse
import datetime as dt
import pathlib
import shutil
import sys

from ryness.batch_ingest import ingest_with_timeout


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup and rebuild ryness.db from PDFs.")
    parser.add_argument(
        "folder",
        nargs="?",
        default=str(
            pathlib.Path("ryness")
            / "RynessReportsPDFs"
            / "RynessReports-20251221T191304Z-1-001"
            / "RynessReports"
        ),
        help="Folder to scan for PDFs.",
    )
    parser.add_argument("--db", default="ryness.db", help="SQLite database path.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Per-PDF ingest timeout in seconds (0 disables).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped backup of the existing DB.",
    )
    args = parser.parse_args()

    root = pathlib.Path(args.folder)
    if not root.exists():
        print(f"Folder not found: {root}", file=sys.stderr)
        return 1

    db_path = pathlib.Path(args.db)
    if db_path.exists() and not args.no_backup:
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = db_path.with_name(f"{db_path.name}.bak-{ts}")
        shutil.copy2(db_path, backup_path)
        print(f"Backed up {db_path} -> {backup_path}")

    if db_path.exists():
        db_path.unlink()

    pdfs = sorted(root.rglob("*.pdf"))
    if not pdfs:
        print("No PDFs found.")
        return 0

    failed = 0
    for pdf in pdfs:
        try:
            status, detail = ingest_with_timeout(pdf, str(db_path), args.timeout)
            if status == "ok":
                print(f"OK: {pdf}")
            elif status == "timeout":
                failed += 1
                print(f"TIMEOUT: {pdf} ({detail})", file=sys.stderr)
            else:
                failed += 1
                msg = (detail or "Unknown error").strip()
                print(f"FAIL: {pdf}\n{msg}", file=sys.stderr)
        except KeyboardInterrupt:
            print("Interrupted by user.", file=sys.stderr)
            return 130
        except Exception as exc:
            failed += 1
            print(f"FAIL: {pdf} ({exc})", file=sys.stderr)

    if failed:
        print(f"Completed with {failed} failures.", file=sys.stderr)
        return 2

    print("Completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
