# Contributing

Useful contributions include synthetic bug reproducers, disclosure adapters with documented field meanings, and tests for mathematical or data-quality failures.

Use Python 3.12 or later and install python -m pip install -e ".[dev]". Run pytest, ruff check and ruff format --check as shown in README.md.

Use fixtures with independently calculable expectations. Preserve dates, NAV denominators, currencies and adjustments. Unknown holdings must not silently become zero or cash.

Adapters need schema validation and examples with documented reuse permission. Public tests must run without credentials or licensed data.

Bug reports should include commands, versions and minimal synthetic inputs. Remove account identifiers, portfolio amounts, tokens, home paths and private reports.

The project calculates research evidence. Keep numerical calculations deterministic and independent of language-model output.
