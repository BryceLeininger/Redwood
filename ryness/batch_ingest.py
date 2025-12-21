import argparse
import pathlib
import sys

from .ingest import ingest


def main():
    parser = argparse.ArgumentParser(description="Ingest all Ryness Report PDFs in a folder.")
    parser.add_argument("folder", help="Folder to scan for PDFs.")
    parser.add_argument("--db", default="ryness.db", help="SQLite database path.")
    args = parser.parse_args()

    root = pathlib.Path(args.folder)
    if not root.exists():
        print(f"Folder not found: {root}", file=sys.stderr)
        sys.exit(1)

    pdfs = sorted(root.rglob("*.pdf"))
    if not pdfs:
        print("No PDFs found.")
        return

    failed = 0
    for pdf in pdfs:
        try:
            ingest(pdf, args.db)
            print(f"OK: {pdf}")
        except Exception as exc:
            failed += 1
            print(f"FAIL: {pdf} ({exc})", file=sys.stderr)

    if failed:
        print(f"Completed with {failed} failures.", file=sys.stderr)
        sys.exit(2)
    print("Completed successfully.")


if __name__ == "__main__":
    main()
