# Portfolio Evidence Lab

Reproducible fund look-through and portfolio risk research.

Know what you own, where your risk comes from, and what the data cannot tell you.

[中文说明](README.zh-CN.md)

## Try it offline

Use Python 3.12 or later in a virtual environment. From a source checkout:

```sh
python -m pip install -e .
portfolio-lab demo --destination demo-workspace
```

Open the HTML report printed by the command. Running the installed demo needs no account, API key or network connection. Installation requires Python dependencies.

All four products, prices, holdings and amounts are synthetic. The report displays that label and its actual provenance.

| Independently calculable fixture result | Value |
| --- | ---: |
| Identified underlying NAV share | 71.9% |
| Unresolved share | 28.1% |
| Exposure to fictional US:SYNTH_A | 31.15% |

The example includes overlapping equity funds, a defensive fund and a feeder. Unreported assets remain unknown at each recursion level.

## What it does

- Preserves disclosure dates, publication dates, source identifiers and scope.
- Recursively expands funds, detects cycles and reconciles weight totals.
- Reports known overlap and a conservative upper bound for incomplete disclosures.
- Estimates covariance, Euler volatility contributions, drawdown and empirical weekly CVaR.
- Compares constrained research candidates, costs and a chronological holdout.
- Records input/source hashes and content-addressed evidence for replay.

All numbers come from Python calculations. Research candidates are conditional model outputs, not orders or return forecasts.

## Bring local data

```sh
portfolio-lab import-csv positions.csv --output private/ssot/raw.json
portfolio-lab run --root .
```

Also provide a research configuration, CNY total-return NAV observations and normalized holdings. See [input contracts](docs/DATA.md).

## Verify and replay

Replace RUN_ID with the printed run identifier:

```sh
portfolio-lab verify demo-workspace/private/runs/RUN_ID/manifest.json --root demo-workspace
portfolio-lab replay demo-workspace/private/runs/RUN_ID/manifest.json --root demo-workspace --destination replay-workspace
```

Replay requires the recorded Python and dependency versions. It restores saved inputs and source to a new directory. Hash verification detects changes; it does not establish that an original disclosure was accurate.

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m build
```

Tests exercise mathematical reconciliations, input failures, the production demo path, replay and tamper detection. See [contributing](CONTRIBUTING.md).

## Privacy and data

Public examples and screenshots use synthetic data or data with documented reuse permission. The public export excludes runtime evidence, reports, account configuration and Git history. See [security and data policy](SECURITY.md).

The code is MIT licensed. Third-party data keeps its own terms. Source adapters do not grant data access or redistribution rights.

## Related projects

[QuantStats](https://github.com/ranaroussi/quantstats) provides performance analytics.
[Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) provides portfolio optimization.
[fund-overlap-lab](https://github.com/JordiCorbilla/fund-overlap-lab) supports fund overlap and recursive expansion.

This project focuses on explicit disclosure gaps and reproducible research evidence. No uniqueness or adoption claim is implied.
