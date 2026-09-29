# Pediatric LLM Abstraction Benchmark

Code, synthetic data, run logs, and results for the paper

> **Assessing Large Language Model Performance for Pediatric Clinical Data Abstraction Using Synthetic Patient Records**
> Vinod Rufus Motani and Anil Kumar Bayya

Everything here is synthetic. No real patient data, protected health information, or
institutional material was used at any stage.

## Milestone tags

| Tag | Meaning |
|---|---|
| `prereg-peds_abstraction-v1` | design frozen (`config/prereg_peds_abstraction.yaml`, prompts, schema) before the first model call |
| `gold-peds_abstraction-v1` | corpus and gold standard frozen (`data/peds_abstraction/`) |
| `results-peds_abstraction-v1` | pre-registered analysis complete (`results/peds_abstraction/`) |

Every change after a tag is recorded in `DEVIATIONS.md` and reported in the paper.

## Layout

- `config/prereg_peds_abstraction.yaml` - pre-registration (hypothesis, models, metrics, matching rules)
- `prompts/`, `schema/` - the exact prompts and JSON schema sent to the models
- `src/peds_abstraction/` - `make_scenarios.py`, `generate_records.py` (corpus and gold construction), `run_models.py` (execution), `score.py`, `errors.py`, `report.py`
- `src/common/` - provider adapters and run logging (`runner.py`), normalization, statistics, identifier/institution audit (`audit.py`)
- `data/peds_abstraction/` - 160 records, scenario specifications, gold abstractions, plausibility-screen findings
- `runs/peds_abstraction/` - one JSON line per successful model call (model version, timestamp, latency, token usage, raw response, parse outcome)
- `results/peds_abstraction/` - every table and figure behind the paper
- `tools/peds_*.py` - declared secondary analyses, adjudication, figures, construction-validity check, clinician-review table
- `tests/` - unit tests; `DEVIATIONS.md` - the post-tag change log

## Reproduce

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
python src/common/audit.py                       # identifier and institution audit: must print 0 finding(s)
python tools/peds_gold_narrative_check.py        # every gold value appears in its narrative: must print misses: 0
python src/peds_abstraction/score.py             # rebuilds results/peds_abstraction/*.csv from runs/
python tools/peds_extra_stats.py && python tools/peds_secondary_stats.py
python tools/peds_adjudicate_unsupported.py && python tools/peds_v2_analyses.py && python tools/peds_figures.py
```

Re-running the models needs API keys in `.env` (see `.env.example`) and will produce new
outputs; the paper's numbers come from the logged runs in `runs/`.

Re-running the analysis on another operating system reproduces every value reported in the
paper. Two files are not byte-identical across platforms: `pairwise.csv` and
`secondary_band_setting.csv` differ in the last floating-point digit, and the bootstrap
confidence-interval bounds in `secondary_setting.csv` (not reported in the paper; point
estimates identical) depend on directory enumeration order and can move at the third
decimal. Figures are re-rendered by matplotlib and differ at the pixel level only.

## Provenance of this repository

This public repository was derived from the authors' private working repository with
`git filter-repo`. Paths and unit tests belonging to other studies were removed; the
institution blocklist in `src/common/audit.py` is stored as SHA-256 digests rather than clear
text; local filesystem paths in one operational log were replaced by `<repo>`. All data,
run logs, results, prompts, configuration, commit dates, and tag positions are unchanged.
