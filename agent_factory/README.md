# Agent Factory

`agent_factory` is a meta-agent project: one factory agent creates other machine-learning specialist agents.

Each generated specialist agent has:
- A trained task model (`classification` or `regression`) from labeled CSV data.
- A topic knowledge index from local docs (`.txt`, `.md`, `.csv`, `.json`, `.log`, `.rst`).
- Runtime commands for task prediction and topic Q&A.

## Quick Start

1. Install dependencies:

```bash
python -m pip install -r agent_factory/requirements.txt
```

2. Create a specialist agent:

```bash
python -m agent_factory.cli create-agent \
  --name "SupportRouter" \
  --description "Routes user support requests to the right queue." \
  --topic "Customer Support" \
  --task-type classification \
  --dataset agent_factory/examples/support_training.csv \
  --knowledge agent_factory/examples/knowledge \
  --input-column input \
  --target-column target \
  --output-dir generated_agents
```

3. Run task prediction:

```bash
python -m agent_factory.cli predict \
  --agent-dir generated_agents/supportrouter_YYYYMMDD_HHMMSS \
  --input "I was charged twice this month"
```

4. Ask a topic question:

```bash
python -m agent_factory.cli ask \
  --agent-dir generated_agents/supportrouter_YYYYMMDD_HHMMSS \
  --question "How should billing disputes be handled?" \
  --top-k 3
```

5. Inspect agent metadata:

```bash
python -m agent_factory.cli describe --agent-dir generated_agents/supportrouter_YYYYMMDD_HHMMSS
```

6. List all generated agents:

```bash
python -m agent_factory.cli list --output-dir generated_agents
```

## Dataset Format

Training dataset must be CSV with at least two columns:

- `input`: text used for training.
- `target`: label (classification) or numeric value (regression).

You can rename these with `--input-column` and `--target-column`.

## Notes

- Small datasets (<10 rows) are trained and evaluated on the same data.
- Larger datasets use a holdout split for evaluation metrics.
- Topic answers are retrieval-based excerpts from indexed knowledge docs.

## Bootstrap the Three Requested Agents

This project includes a helper script that creates:
- `OutlookEmailManager`
- `LandDealUnderwriter`
- `HousingMarketResearcher`

Run:

```bash
python -m agent_factory.bootstrap_requested_agents
```
