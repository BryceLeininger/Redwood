import argparse
import pathlib
import sys
import traceback

import multiprocessing as mp

from .ingest import ingest


def _ingest_worker(pdf_path, db_path, queue):
    try:
        ingest(pdf_path, db_path)
        queue.put(("ok", None))
    except BaseException:
        queue.put(("error", traceback.format_exc()))


def ingest_with_timeout(pdf_path, db_path, timeout_s):
    if not timeout_s or timeout_s <= 0:
        ingest(pdf_path, db_path)
        return "ok", None

    queue = mp.Queue(maxsize=1)
    proc = mp.Process(target=_ingest_worker, args=(str(pdf_path), str(db_path), queue))
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(10)
        return "timeout", f"Timed out after {timeout_s}s"

    try:
        status, detail = queue.get_nowait()
    except Exception:
        status, detail = "error", "Worker exited without reporting status."

    if status == "ok":
        return "ok", None
    return "error", detail


def main():
    parser = argparse.ArgumentParser(description="Ingest all Ryness Report PDFs in a folder.")
    parser.add_argument("folder", help="Folder to scan for PDFs.")
    parser.add_argument("--db", default="ryness.db", help="SQLite database path.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Per-PDF ingest timeout in seconds (0 disables).",
    )
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
            status, detail = ingest_with_timeout(pdf, args.db, args.timeout)
            if status == "ok":
                print(f"OK: {pdf}")
            elif status == "timeout":
                failed += 1
                print(f"TIMEOUT: {pdf} ({detail})", file=sys.stderr)
            else:
                failed += 1
                msg = detail.strip() if detail else "Unknown error"
                print(f"FAIL: {pdf}\n{msg}", file=sys.stderr)
        except KeyboardInterrupt:
            print("Interrupted by user.", file=sys.stderr)
            sys.exit(130)
        except Exception as exc:
            failed += 1
            print(f"FAIL: {pdf} ({exc})", file=sys.stderr)

    if failed:
        print(f"Completed with {failed} failures.", file=sys.stderr)
        sys.exit(2)
    print("Completed successfully.")


if __name__ == "__main__":
    main()
