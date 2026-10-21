# Local input contracts

## Workspace

Run from a source checkout. The demo also creates a self-contained source/evidence workspace after wheel installation. Runtime evidence lives under private/ and must never be committed.

| Path | Content |
| --- | --- |
| private/ssot/raw.json | Validated positions snapshot |
| private/nav.csv | CNY total-return NAV observations |
| private/holdings.json | Normalized disclosure records |
| config/research.json | Research date, window and constraints |
| src/portfolio_lab/ | Source retained for replay |
| pyproject.toml | Source metadata retained for replay |

Use a separate workspace for real data. Do not relabel synthetic prices as market observations.

## Positions CSV

```csv
code,name,market_value,as_of,venue
990001,Fictional fund A,6000,2025-06-27,synthetic
990002,Fictional fund B,4000,2025-06-27,synthetic
```

All examples here are synthetic. Required columns are shown above. Preserve six-digit identifiers as text, positive finite amounts and one snapshot date. Optional columns follow Position in models.py. Account identifiers and unsupported columns are rejected.

```sh
portfolio-lab import-csv positions.csv --output private/ssot/raw.json
```

Existing snapshots are never overwritten. The receipt records the CSV hash without its absolute path.

## NAV CSV

```csv
code,date,adjusted_nav,currency,adjustment,source_id
990001,2025-06-20,1.0000,CNY,total_return,synthetic-example
990001,2025-06-27,1.0100,CNY,total_return,synthetic-example
990002,2025-06-20,1.0000,CNY,total_return,synthetic-example
990002,2025-06-27,1.0050,CNY,total_return,synthetic-example
```

This fragment is too short for a run. Supply at least the configured number of complete weekly returns, 40 by default.

The supplier must establish dividend/split-adjusted total-return NAVs in CNY. The adapter checks that declaration, finite positive values, unique product/date pairs and exact portfolio identities. It cannot independently prove the adjustment calculation.

Use ISO dates YYYY-MM-DD. Missing returns are not filled. The engine uses Friday endpoints with a bounded backward observation age. private/nav.csv selects this adapter; otherwise existing versioned-provider adapters apply.

## Holdings JSON

```json
[{"fund":"990001","security":"US:SYNTH_A","name":"Fictional company A",
"weight":0.45,"holding_date":"2025-03-31","published_date":"2025-05-01",
"source_id":"synthetic-example","scope":"partial","kind":"equity"}]
```

Weights are fractions of fund NAV. A lone 45% holding leaves 55% unknown. A fund record expands recursively when its security identifier has its own rows. An omitted product stays unresolved.

Preserve sources, dates and scope. Future disclosures, mixed dates within a fund, duplicate securities and cycles are rejected. A missing publication date produces an explicit point-in-time limitation.

## Configuration

```json
{"as_of":"2025-06-27","start":"2023-12-22","min_observations":40,"bootstrap_samples":100}
```

Write this to config/research.json, then run portfolio-lab run --root . from the workspace. Optional constraints follow ResearchConfig. Currency is CNY and frequency is weekly. Other currencies require verified conversion before import.

## Outputs

The run directory contains an HTML report, decision.json, exposure/covariance/return CSVs and manifest.json. Runtime outputs stay local; sharing a report is a separate decision.

The manifest records inputs, workspace source, dependency versions and hashes. Replay needs the recorded environment. The demo copies installed package source so wheel users can also replay.
