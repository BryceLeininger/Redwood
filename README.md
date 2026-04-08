# Land Due Diligence Agent

Portable Python CLI prototype for reviewing seller-provided land acquisition diligence packages. The current priority is first-test reliability: local parsing, visible run reporting, clear output folders, and easy operator inspection.

## First-Test Readiness

The first review pass surfaced a few items that needed to be tightened before using a real diligence package:

- Repeated runs previously wrote into the same deal output folder and could overwrite earlier results. This now writes each run into a timestamped subfolder.
- There was no standalone operational summary or error report. The CLI now writes both on every run, including partial-failure runs.
- File-level parse warnings were easy to miss. The run log and run summary now show which files parsed cleanly, parsed with warnings, or failed.
- The repo did not include an example deal-folder layout. A committed sample structure now lives under `examples/sample_deal_input/`.

This is still an MVP. Scanned PDFs now trigger selective OCR fallback page by page when the text layer is empty or unusually weak, but OCR quality still depends on local Tesseract and Poppler installation.

## Architecture

- `src/land_due_diligence_agent/ingestion`
  discovers supported files from an input directory
- `src/land_due_diligence_agent/parsing`
  extracts text from PDF, DOCX, XLSX, CSV, TXT, and MD files
- `src/land_due_diligence_agent/analysis`
  runs deterministic risk heuristics, missing-item checks, reading-order scoring, and deal-level synthesis
- `src/land_due_diligence_agent/llm`
  abstracts summary refinement behind a provider interface
  default `heuristic` mode stays local-only
  optional `openai` mode can refine summaries if configured
- `src/land_due_diligence_agent/output`
  writes Markdown deliverables plus operational reports
- `src/land_due_diligence_agent/utils`
  provides shared helpers for text normalization, logging, and path handling

## Repo Structure

```text
.
|-- .env.example
|-- .gitignore
|-- README.md
|-- pyproject.toml
|-- requirements.txt
|-- data
|   |-- input
|   |   `-- .gitkeep
|   `-- output
|       `-- .gitkeep
|-- examples
|   `-- sample_deal_input
|       |-- README.md
|       |-- 01_overview
|       |-- 02_entitlements
|       |-- 03_environmental
|       |-- 04_civil_and_geotech
|       |-- 05_utilities
|       |-- 06_title_and_survey
|       |-- 07_schedule_and_budget
|       `-- 08_misc_correspondence
|-- src
|   `-- land_due_diligence_agent
|       |-- __init__.py
|       |-- __main__.py
|       |-- cli.py
|       |-- config.py
|       |-- models.py
|       |-- analysis
|       |-- ingestion
|       |-- llm
|       |-- output
|       |-- parsing
|       `-- utils
`-- tests
```

## Sample Input Organization

Use the sample folder at `examples/sample_deal_input/` as the template for one deal. For a real run, mirror that structure under `data/input/<deal-folder>/`.

Example:

```text
data/input/acme-ranch/
|-- 01_overview/
|-- 02_entitlements/
|-- 03_environmental/
|-- 04_civil_and_geotech/
|-- 05_utilities/
|-- 06_title_and_survey/
|-- 07_schedule_and_budget/
`-- 08_misc_correspondence/
```

The CLI recursively scans the whole deal folder, so the subfolders are for operator clarity and review discipline, not strict parser requirements.

## Setup

1. Clone the repository.
2. Create and activate a virtual environment.
3. Install dependencies.
4. Copy `.env.example` to `.env`.
5. Keep `LLM_PROVIDER=heuristic` for the first live test unless you intentionally want external LLM refinement.
6. Place one real deal package under `data/input/<deal-folder>/`.
7. Run the CLI against that one folder.

### Windows PowerShell

```powershell
git clone <your-repo-url> Redwood
cd Redwood
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS / Linux

```bash
git clone <your-repo-url> Redwood
cd Redwood
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### OCR Prerequisites For Scanned PDFs

Python dependencies for OCR are installed automatically through `requirements.txt`, but the OCR path also needs local system tools:

- `Tesseract OCR`
- `Poppler` for `pdf2image`

Windows:

1. Install Tesseract OCR and make sure `tesseract.exe` is on `PATH`.
2. Install Poppler and make sure `pdftoppm.exe` is on `PATH`.
3. If either tool is not on `PATH`, set these in `.env`:

```env
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\path\to\poppler\Library\bin
```

macOS with Homebrew:

```bash
brew install tesseract poppler
```

Ubuntu / Debian:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

## Run One Deal Folder

Place a single deal under `data/input/acme-ranch/`, then run:

```powershell
land-dd --input-folder data/input/acme-ranch --deal-name "Acme Ranch"
```

You can also run the package directly:

```powershell
python -m land_due_diligence_agent --input-folder data/input/acme-ranch --deal-name "Acme Ranch"
```

Useful optional flags:

- `--mode fast`
- `--mode full`
- `--output-folder data/output`
- `--llm-provider heuristic`
- `--llm-provider openai`
- `--log-level DEBUG`

Mode behavior:

- `fast` is the default quick-read path and writes only the executive summary, light key risks, seller questions, run summary, and error report.
- `full` keeps the full decision-grade workflow, including contradictions, deep synthesis, reading order, document summaries, and the IC brief.

## What Gets Logged

Each run writes `run.log` in the run output folder and logs:

- analysis mode
- run ID, input folder, and output folder
- number of supported files found
- each file parsed successfully
- each file parsed with warnings
- which documents and pages required OCR
- each file that failed
- approximate LLM calls made
- final counts for found, parsed successfully, and failed

## Output Layout

Each run now writes to a timestamped folder:

```text
data/output/<deal-slug>/<YYYYMMDD_HHMMSS>/
```

Expected outputs in `full` mode:

- `00_run_summary.md`
- `01_executive_summary.md`
- `02_key_risks.md`
- `03_recommended_reading_order.md`
- `04_seller_questions.md`
- `05_document_summaries.md`
- `06_missing_diligence_items.md`
- `07_deal_synthesis.md`
- `08_error_report.md`
- `run.log`

Expected outputs in `fast` mode:

- `00_run_summary.md`
- `01_executive_summary.md`
- `02_key_risks.md`
- `04_seller_questions.md`
- `08_error_report.md`
- `run.log`

Inspect these in order for the first real test:

1. `00_run_summary.md`
2. `08_error_report.md`
3. `01_executive_summary.md`
4. `05_document_summaries.md`

## Run Summary and Error Report

`00_run_summary.md` includes:

- analysis mode
- approximate LLM calls
- number of files found
- number parsed successfully
- number failed
- OCR fallback activity by document and page
- per-file status
- output files created

`08_error_report.md` includes:

- OCR fallback activity by document and page
- run-level errors
- failed files
- files parsed with warnings
- extraction issues that were passed into analysis

## Configuration

Default local-only mode:

```env
LLM_PROVIDER=heuristic
```

Optional OpenAI refinement:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1
```

If you later need Azure OpenAI or another provider, the abstraction point is under `src/land_due_diligence_agent/llm/`.

## Testing

```powershell
python -m unittest discover -s tests -v
```

## Post-First-Test Upgrade Priorities

- Expand citations deeper into per-document evidence excerpts and spreadsheet-specific references.
- Tune OCR thresholds and image preprocessing for large scanned plan sets and cost exhibits.
- Tune the heuristic rules against observed false positives and false negatives from the first real deal.
- Add structured JSON export alongside Markdown for downstream workflows.
- Add local model support and Azure-compatible provider wiring through the existing abstraction layer.
- Add vector search for retrieval across larger diligence packages.
- Add multi-deal comparison workflows.
- Add a lightweight local UI only after the CLI workflow is stable in real testing.
