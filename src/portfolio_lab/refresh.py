"""A scheduler-compatible refresh boundary. No implicit network or paid-provider calls."""

import json
from datetime import UTC, datetime

from .engine import run_research
from .evidence import DataError, read_json, write_bytes_atomic, write_json
from .normalize import normalize


def refresh_once(root, catalog, config, snapshot, online_market=False, _locked=False):
    if not _locked:
        from .snapshot_update import update_guard

        with update_guard(root):
            return refresh_once(root, catalog, config, snapshot, online_market, _locked=True)
    status = {"started_at": datetime.now(UTC).isoformat(), "mode": "offline evidence refresh"}
    market_path = root / "private/market_catalog.json"
    proxy_path = root / "private/market_proxies.json"
    protected = [
        root / "private" / name
        for name in [
            "market_catalog.json",
            "market_proxies.json",
            "latest.json",
            "holdings.json",
            "disclosure_qa.json",
            "derivatives.json",
            "normalization_manifest.json",
        ]
    ]
    backups = {p: p.read_bytes() if p.exists() else None for p in protected}
    previous_market = read_json(market_path) if market_path.exists() else None
    try:
        if online_market:
            from .models import ResearchConfig
            from .providers import load_nav
            from .public_nav import collect
            from .ssot import parse_snapshot

            cfg = ResearchConfig.model_validate(read_json(root / config))
            positions, _ = parse_snapshot(read_json(root / snapshot))
            if positions[0].as_of != cfg.as_of:
                raise DataError("SSOT/config dates differ; no online collection started")
            codes = [p.code for p in positions]
            if proxy_path.exists():
                from .proxy_refresh import collect_proxies

                proxy_batch = (
                    root
                    / "private/raw/factors"
                    / ("refresh-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
                )
                status["proxy_batch"] = str(proxy_batch)
                proxy_catalog = collect_proxies(root, proxy_batch, cfg.start, cfg.as_of, proxy_path)
            else:
                proxy_catalog = None
            reference, _ = load_nav(root / "private/raw/wind", codes)
            batch = (
                root / "private/raw/vendor" / ("eastmoney-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
            )
            status.update(mode="public NAV collection and evidence refresh", batch=str(batch))
            records = collect(codes, batch, str(cfg.start), reference)
            updated = {}
            for row in records:
                entry = row["entry"].copy()
                for key in ["page", "nav"]:
                    entry[key] = (batch / entry[key]).relative_to(root).as_posix()
                entry["evidence_paths"] = [
                    p.relative_to(root).as_posix() for p in batch.glob("*.request.json")
                ]
                entry["evidence_paths"].append((batch / "collection.json").relative_to(root).as_posix())
                updated[row["code"]] = entry
            write_json(batch / "candidate-market-catalog.json", updated)
            if previous_market is not None:
                write_json(batch / "previous-market-catalog.json", previous_market)
            write_json(market_path, updated)
            if proxy_catalog is not None:
                write_json(proxy_path, proxy_catalog)
        count = normalize(root, root / catalog)
        out, result = run_research(root, root / config, root / snapshot, root / "private/holdings.json")
        status.update(
            status="SUCCESS_WITH_LIMITS",
            run_id=result["run_id"],
            holdings=count,
            research_as_of=result["as_of"],
            report=str(out / "Portfolio_Decision_Report.html"),
        )
    except Exception as exc:
        for path, payload in backups.items():
            if payload is not None:
                write_bytes_atomic(path, payload)
            else:
                path.unlink(missing_ok=True)
        status.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        status["finished_at"] = datetime.now(UTC).isoformat()
        write_json(root / "private/update_status.json", status)
        log = root / "private/update_history.jsonl"
        with log.open("a", encoding="utf8") as f:
            f.write(json.dumps(status, ensure_ascii=False) + "\n")
    return status["report"]
