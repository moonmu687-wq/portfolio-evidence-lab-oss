"""An explicitly synthetic, offline case using the production research engine."""

import csv
import importlib.metadata
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .csv_inputs import portfolio_csv
from .evidence import DataError, write_json


def create_demo(destination: Path):
    root = destination.resolve()
    if root.exists():
        raise DataError("Demo destination must not exist; choose a new directory")
    root.mkdir(parents=True)
    package = root / "src/portfolio_lab"
    package.mkdir(parents=True)
    for source in Path(__file__).resolve().parent.glob("*.py"):
        shutil.copyfile(source, package / source.name)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "portfolio-evidence-lab"\n'
        f'version = "{__version__}"\nrequires-python = ">=3.12"\n',
        encoding="utf8",
    )
    packages = ["numpy", "pandas", "scipy", "scikit-learn", "pydantic", "pypdf"]
    (root / "requirements.lock").write_text(
        "".join(f"{p}=={importlib.metadata.version(p)}\n" for p in packages), encoding="utf8"
    )
    private = root / "private"
    private.mkdir()
    codes = ["990001", "990002", "990003", "990004"]
    names = ["Synthetic growth A", "Synthetic growth B", "Synthetic defensive", "Synthetic feeder"]
    dates = pd.date_range(end="2025-06-27", periods=80, freq="W-FRI")
    positions = root / "positions.csv"
    with positions.open("w", encoding="utf8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "name", "market_value", "as_of", "venue"])
        for code, name, amount in zip(codes, names, [3500, 2500, 2500, 1500]):
            writer.writerow([code, name, amount, "2025-06-27", "synthetic"])
    snapshot = portfolio_csv(positions)
    snapshot["data_kind"] = "synthetic"
    snapshot["source_observation"]["provider"] = "Deterministic synthetic fixture; no real account or prices"
    write_json(private / "ssot/raw.json", snapshot)
    rng = np.random.default_rng(20261021)
    factors = rng.normal(size=(len(dates) - 1, 3))
    shocks = np.column_stack(
        [
            0.001 + 0.025 * factors[:, 0],
            0.001 + 0.022 * factors[:, 0] + 0.008 * factors[:, 1],
            0.0005 + 0.006 * factors[:, 2],
            0.0008 + 0.019 * factors[:, 0] + 0.004 * factors[:, 2],
        ]
    )
    levels = np.vstack([np.ones(4), np.cumprod(1 + shocks, axis=0)])
    with (private / "nav.csv").open("w", encoding="utf8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "date", "adjusted_nav", "currency", "adjustment", "source_id"])
        for day, values in zip(dates, levels):
            for code, value in zip(codes, values):
                writer.writerow(
                    [code, str(day.date()), format(value, ".12g"), "CNY", "total_return", "synthetic-v1"]
                )
    holdings = []
    specs = [
        (codes[0], "US:SYNTH_A", 0.45, "equity"),
        (codes[0], "US:SYNTH_B", 0.25, "equity"),
        (codes[1], "US:SYNTH_A", 0.40, "equity"),
        (codes[1], "US:SYNTH_C", 0.20, "equity"),
        (codes[2], "SYNTH_BOND", 0.80, "bond"),
        (codes[2], "SYNTH_CASH", 0.10, "cash"),
        (codes[3], codes[0], 0.80, "fund"),
        (codes[3], "SYNTH_GOLD", 0.10, "gold"),
    ]
    for fund, security, weight, kind in specs:
        holdings.append(
            {
                "fund": fund,
                "security": security,
                "name": security,
                "weight": weight,
                "holding_date": "2025-03-31",
                "published_date": "2025-05-01",
                "source_id": "synthetic-v1",
                "scope": "partial",
                "kind": kind,
            }
        )
    write_json(private / "holdings.json", holdings)
    write_json(
        root / "config/research.json",
        {
            "start": str(dates[0].date()),
            "as_of": "2025-06-27",
            "min_observations": 40,
            "bootstrap_samples": 100,
        },
    )
    (root / "SYNTHETIC_DATA.md").write_text(
        "# Synthetic demonstration\n\nAll names, identifiers, amounts, prices and disclosures are fictional.\n"
        "Expected identified NAV share: 71.9%. Unknown share: 28.1%.\n"
        "Expected exposure to US:SYNTH_A: 31.15%. No real account data is included.\n",
        encoding="utf8",
    )
    return root


def run_demo(destination: Path):
    from .engine import run_research

    root = create_demo(destination)
    return run_research(
        root, root / "config/research.json", root / "private/ssot/raw.json", root / "private/holdings.json"
    )
