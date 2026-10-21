import argparse
import sys
from pathlib import Path

from .evidence import DataError, read_json, verify_manifest, write_json


def main():
    parser = argparse.ArgumentParser(description="Auditable real portfolio research")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run an offline synthetic case; no account or API key needed")
    demo.add_argument("--destination", type=Path, required=True)
    csv_import = sub.add_parser("import-csv", help="Validate a local positions CSV and save a snapshot")
    csv_import.add_argument("portfolio", type=Path)
    csv_import.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run", help="Recompute offline from versioned evidence")
    run.add_argument("--root", type=Path, default=Path.cwd())
    run.add_argument("--config", default="config/research.json")
    run.add_argument("--snapshot", default="private/ssot/raw.json")
    run.add_argument("--holdings", default="private/holdings.json")
    verify = sub.add_parser("verify", help="Verify saved evidence and output hashes")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--root", type=Path, default=Path.cwd())
    verify.add_argument(
        "--archived", action="store_true", help="Verify frozen inputs instead of current working files"
    )
    replay = sub.add_parser(
        "replay", help="Rebuild a historical run from content-addressed evidence and source"
    )
    replay.add_argument("manifest", type=Path)
    replay.add_argument("--destination", type=Path, required=True)
    replay.add_argument("--root", type=Path, default=Path.cwd())
    sync = sub.add_parser("sync-sheet", help="Read SSOT with an externally provisioned read-only OAuth token")
    sync.add_argument("--id", required=True)
    sync.add_argument("--output", type=Path, required=True)
    norm = sub.add_parser(
        "normalize", help="Rebuild holdings from raw evidence and a declared acquisition catalog"
    )
    norm.add_argument("--root", type=Path, default=Path.cwd())
    norm.add_argument("--catalog", default="private/acquisition.json")
    refresh = sub.add_parser("refresh", help="Offline normalize, validate, compute and log success/failure")
    refresh.add_argument("--root", type=Path, default=Path.cwd())
    refresh.add_argument("--catalog", default="private/acquisition.json")
    refresh.add_argument("--config", help="Defaults to latest successfully adopted input configuration")
    refresh.add_argument("--snapshot", help="Defaults to latest successfully adopted snapshot")
    refresh.add_argument(
        "--online-market",
        action="store_true",
        help="Collect and validate public NAVs for all snapshot products before computing",
    )
    update = sub.add_parser("update", help="Adopt a real SSOT snapshot, follow its date and recompute")
    update.add_argument("--root", type=Path, default=Path.cwd())
    source = update.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path, help="Authorized connector snapshot bundle")
    source.add_argument("--sheet", help="Read-only Google Sheets ID; requires external OAuth token")
    update.add_argument("--config", help="Preserve active constraints by default; only date follows SSOT")
    update.add_argument("--catalog", default="private/acquisition.json")
    update.add_argument("--online-market", action="store_true")
    public = sub.add_parser("collect-public-nav", help="Acquire and cross-check public third-party fund NAVs")
    public.add_argument("--codes", nargs="+", required=True)
    public.add_argument("--output", type=Path, required=True)
    public.add_argument("--start", required=True)
    public.add_argument("--reference", type=Path, default=Path("private/raw/wind"))
    public_reports = sub.add_parser(
        "collect-public-reports", help="Collect manager disclosure PDFs from a public mirror"
    )
    public_reports.add_argument("--codes", nargs="+", required=True)
    public_reports.add_argument("--output", type=Path, required=True)
    public_reports.add_argument("--report-title", required=True)
    public_reports.add_argument("--as-of", required=True)
    basket = sub.add_parser("collect-ishares", help="Acquire dated investment-book basket; not NAV evidence")
    basket.add_argument("--ticker", required=True)
    basket.add_argument("--holding-date", required=True)
    basket.add_argument("--output", type=Path, required=True)
    issuer = sub.add_parser(
        "collect-efunds", help="Read official issuer NAV and report sources into a new batch"
    )
    issuer.add_argument("--codes", nargs="+", required=True)
    issuer.add_argument("--output", type=Path, required=True)
    issuer.add_argument("--report-title", default="2026年中期报告")
    hwabao = sub.add_parser("collect-fsfund", help="Read verified Hwabao product evidence into a new batch")
    hwabao.add_argument("--code", default="501312")
    hwabao.add_argument("--output", type=Path, required=True)
    hwabao.add_argument("--report-title", default="2026年中期报告")
    exchange = sub.add_parser("collect-sse", help="Collect versioned official SSE fund reports")
    exchange.add_argument("--codes", nargs="+", required=True)
    exchange.add_argument("--output", type=Path, required=True)
    exchange.add_argument("--start", required=True)
    exchange.add_argument("--end", required=True)
    exchange.add_argument("--report-title", required=True)
    args = parser.parse_args()
    try:
        if args.command == "demo":
            from .demo import run_demo

            out, _ = run_demo(args.destination)
            print(f"SYNTHETIC DEMONSTRATION: {out / 'Portfolio_Decision_Report.html'}")
        elif args.command == "import-csv":
            from .csv_inputs import portfolio_csv

            if args.output.exists():
                raise DataError("Snapshot already exists; choose a new versioned filename")
            write_json(args.output, portfolio_csv(args.portfolio))
            print("Validated local CSV snapshot saved")
        elif args.command == "update":
            from .snapshot_update import update_snapshot
            from .ssot import read_google_sheet

            root = args.root.resolve()
            bundle = read_google_sheet(args.sheet) if args.sheet else read_json(root / args.snapshot)
            status = update_snapshot(root, bundle, args.config, args.catalog, args.online_market)
            print(f"{status['status']}: {status['report']}")
        elif args.command == "collect-ishares":
            from .official_ishares import collect

            basket = collect(args.ticker, args.holding_date, args.output.resolve())
            print(f"Collected {len(basket['rows'])} investment-book positions; NAV coverage unchanged")
        elif args.command == "collect-public-reports":
            from .public_reports import collect

            reports = collect(args.codes, args.output, args.report_title, args.as_of)
            print(f"Collected {len(reports)} manager report PDFs from public mirror in {args.output}")
        elif args.command == "collect-public-nav":
            from .providers import load_nav
            from .public_nav import collect

            reference, _ = load_nav(args.reference, args.codes)
            records = collect(args.codes, args.output, args.start, reference)
            print(f"Collected and validated public NAVs for {len(records)} products in {args.output}")
        elif args.command == "collect-sse":
            from .official_sse import collect

            rows = collect(args.codes, args.output, args.start, args.end, args.report_title)
            print(f"Collected {len(rows)} official SSE reports in {args.output}")
        elif args.command == "collect-fsfund":
            from .official_fsfund import collect

            collect(args.code, args.output, args.report_title)
            print(f"Collected official Hwabao evidence in {args.output}")
        elif args.command == "collect-efunds":
            from .official_efunds import collect

            rows = collect(args.codes, args.output, args.report_title)
            print(f"Collected official evidence for {len(rows)} funds in {args.output}")
        elif args.command == "run":
            from .engine import run_research
            from .snapshot_update import update_guard

            root = args.root.resolve()
            with update_guard(root):
                out, result = run_research(
                    root, root / args.config, root / args.snapshot, root / args.holdings
                )
            print(f"{result['readiness']}: {out / 'Portfolio_Decision_Report.html'}")
        elif args.command == "verify":
            manifest = read_json(args.manifest)
            verify_manifest(manifest["inputs"], args.root, args.archived)
            verify_manifest(manifest["outputs"], args.root)
            verify_manifest(manifest.get("code", []), args.root, args.archived)
            print("Evidence, code and output hashes verified")
        elif args.command == "replay":
            import importlib.metadata
            import os
            import platform
            import subprocess

            from .evidence import materialize

            manifest = read_json(args.manifest)
            if platform.python_version() != manifest["python"] or any(
                importlib.metadata.version(k) != v for k, v in manifest["packages"].items()
            ):
                raise DataError("Replay environment differs; install recorded dependency versions first")
            dest = args.destination.resolve()
            materialize(manifest, args.root.resolve(), dest)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(dest / "src")
            execution = manifest["execution"]
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "portfolio_lab.cli",
                    "run",
                    "--root",
                    str(dest),
                    "--config",
                    execution["config"],
                    "--snapshot",
                    execution["snapshot"],
                    "--holdings",
                    execution["holdings"],
                ],
                cwd=dest,
                env=env,
                check=False,
            )
            if proc.returncode:
                raise DataError("Historical replay failed")
            latest = read_json(dest / "private/latest.json")
            if latest["run_id"] != manifest["run_id"]:
                raise DataError("Historical replay run identity differs")
            print("Historical replay reproduced run " + latest["run_id"])
        elif args.command == "refresh":
            from .refresh import refresh_once
            from .snapshot_update import select_inputs, update_guard

            root = args.root.resolve()
            with update_guard(root):
                config, snapshot = select_inputs(root, args.config, args.snapshot)
                print(refresh_once(root, args.catalog, config, snapshot, args.online_market, _locked=True))
        elif args.command == "normalize":
            from .normalize import normalize

            root = args.root.resolve()
            print(f"Normalized {normalize(root, root / args.catalog)} disclosed holdings")
        else:
            from .ssot import read_google_sheet

            if args.output.exists():
                raise DataError("Snapshot already exists; choose a new versioned filename")
            write_json(args.output, read_google_sheet(args.id))
            print("Read-only SSOT snapshot saved")
    except (DataError, ValueError, FileNotFoundError) as exc:
        print("FAILED: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
