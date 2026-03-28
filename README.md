# Land Due Diligence Agent

Portable Python CLI prototype for reviewing seller-provided land acquisition diligence packages. The MVP keeps document handling local by default, parses supported files, summarizes each document, synthesizes deal-level findings, flags common land risk themes, and writes structured Markdown outputs.

## MVP Scope

- Input a folder of diligence files
- Support `PDF`, `DOCX`, `XLSX`, `CSV`, `TXT`, and `MD`
- Extract and normalize text locally
- Summarize each document
- Synthesize deal-level findings
- Flag:
  - entitlement status
  - environmental risks
  - flood / drainage issues
  - geotechnical risks
  - offsite obligations
  - utilities / infrastructure issues
  - title / access concerns
  - schedule risks
  - missing diligence items
- Save structured Markdown outputs

## Architecture

- `src/land_due_diligence_agent/ingestion`
  - discovers supported files from an input directory
- `src/land_due_diligence_agent/parsing`
  - handles file-type-specific extraction for PDF, DOCX, XLSX, CSV, TXT, and MD
- `src/land_due_diligence_agent/analysis`
  - runs deterministic risk heuristics, missing-item checks, reading-order scoring, and deal-level synthesis
- `src/land_due_diligence_agent/llm`
  - abstracts summary refinement behind a provider interface
  - default `heuristic` mode is local-only
  - optional `openai` mode can refine summaries if credentials are configured
- `src/land_due_diligence_agent/output`
  - writes the final Markdown deliverables
- `src/land_due_diligence_agent/utils`
  - shared helpers for text normalization, logging, and path handling

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
|-- src
|   `-- land_due_diligence_agent
|       |-- __init__.py
|       |-- __main__.py
|       |-- cli.py
|       |-- config.py
|       |-- models.py
|       |-- analysis
|       |   |-- __init__.py
|       |   |-- heuristics.py
|       |   |-- risk_rules.py
|       |   `-- service.py
|       |-- ingestion
|       |   |-- __init__.py
|       |   `-- discovery.py
|       |-- llm
|       |   |-- __init__.py
|       |   |-- base.py
|       |   |-- factory.py
|       |   |-- heuristic_provider.py
|       |   `-- openai_provider.py
|       |-- output
|       |   |-- __init__.py
|       |   `-- markdown_writer.py
|       |-- parsing
|       |   |-- __init__.py
|       |   |-- docx_parser.py
|       |   |-- pdf_parser.py
|       |   |-- service.py
|       |   |-- spreadsheet_parser.py
|       |   `-- text_parser.py
|       `-- utils
|           |-- __init__.py
|           |-- files.py
|           |-- logging.py
|           `-- text.py
`-- tests
    |-- __init__.py
    |-- test_analysis.py
    |-- test_discovery.py
    `-- test_output.py
```

## Setup

1. Clone the repository.
2. Create and activate a virtual environment.
3. Install dependencies.
4. Copy `.env.example` to `.env`.
5. Update environment variables if needed.
6. Put diligence files under `data/input/<deal-folder>`.
7. Run the CLI.

### Windows PowerShell

```powershell
git clone <your-repo-url> <repo-folder>
cd <repo-folder>
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
land-dd --input-folder data/input/sample-deal --deal-name "Sample Deal"
```

### macOS / Linux

```bash
git clone <your-repo-url> <repo-folder>
cd <repo-folder>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
land-dd --input-folder data/input/sample-deal --deal-name "Sample Deal"
```

## Configuration

The default configuration is local-only:

```env
LLM_PROVIDER=heuristic
```

This means extracted document text stays on the machine and summaries are generated with deterministic heuristics. To enable OpenAI summary refinement, update:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
```

If you later need Azure OpenAI or another provider, the swappable provider layer lives under `src/land_due_diligence_agent/llm`.

## CLI Usage

```powershell
land-dd --input-folder data/input/acme-ranch --deal-name "Acme Ranch"
```

Optional flags:

- `--output-folder data/output`
- `--llm-provider heuristic`
- `--llm-provider openai`
- `--log-level DEBUG`

You can also run the package directly:

```powershell
python -m land_due_diligence_agent --input-folder data/input/acme-ranch
```

## Output Files

Each run writes a deal-specific folder under `data/output/<deal-slug>/` with:

- `00_executive_summary.md`
- `01_key_risks.md`
- `02_recommended_reading_order.md`
- `03_seller_questions.md`
- `04_document_summaries.md`
- `05_missing_diligence_items.md`
- `06_deal_synthesis.md`
- `run.log`

## Privacy Notes

- Input documents are handled locally by default.
- `data/input` and `data/output` are ignored by Git to reduce the risk of committing confidential deal materials.
- If `LLM_PROVIDER=openai`, extracted text may be sent to the configured provider for summary refinement.

## Testing

```powershell
python -m unittest discover -s tests -v
```

## TODO

- Add vector search for semantic retrieval across large diligence packages.
- Add citations and page references in summaries and risk findings.
- Add OCR fallback for scanned PDFs.
- Add local model support through the provider abstraction.
- Add a web UI.
- Add multi-deal comparison workflows.
