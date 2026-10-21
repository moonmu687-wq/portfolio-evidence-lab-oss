"""Versioned SSOT adoption, change evidence and serialized update lifecycle."""

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime

from .evidence import DataError, read_json, write_bytes_atomic, write_json
from .models import ResearchConfig
from .ssot import parse_snapshot


@contextmanager
def update_guard(root):
    path = root / "private/update.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("x", encoding="utf8")
    except FileExistsError:
        raise DataError(
            "An update lock exists; inspect its process before retrying, never auto-delete it"
        ) from None
    try:
        with handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat()}))
            handle.flush()
        yield
    finally:
        path.unlink()


def relative_input(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise DataError("Active research input path escapes project")
    return path.relative_to(root.resolve()).as_posix()


def select_inputs(root, config=None, snapshot=None):
    pointer = root / "private/active_research.json"
    active = read_json(pointer) if pointer.exists() else {}
    return (
        relative_input(root, config or active.get("config", "config/research.json")),
        relative_input(root, snapshot or active.get("snapshot", "private/ssot/raw.json")),
    )


def source_identity(bundle):
    metadata = bundle.get("metadata", {})
    ids = {metadata[k] for k in ["spreadsheetId", "id"] if metadata.get(k)}
    if len(ids) != 1:
        raise DataError("Snapshot source identity missing or inconsistent")
    return ids.pop()


def snapshot_changes(previous, current):
    if source_identity(previous) != source_identity(current):
        raise DataError("New snapshot belongs to a different SSOT")
    old, _ = parse_snapshot(previous)
    new, _ = parse_snapshot(current)
    old_map = {p.code: p.model_dump(mode="json") for p in old}
    new_map = {p.code: p.model_dump(mode="json") for p in new}
    shared = old_map.keys() & new_map.keys()
    changed = []
    for code in sorted(shared):
        fields = {
            k: {"before": old_map[code][k], "after": new_map[code][k]}
            for k in new_map[code]
            if k != "as_of" and old_map[code][k] != new_map[code][k]
        }
        if fields:
            changed.append({"code": code, "fields": fields})
    old_total = sum(p.market_value for p in old)
    new_total = sum(p.market_value for p in new)

    # Account labels are source metadata, not market returns or inferred trades.
    def account_labels(bundle):
        rows = bundle["portfolio"]["values"]
        return {
            dict(zip(rows[0], row)).get("code"): dict(zip(rows[0], row)).get("account")
            for row in rows[1:]
            if row and any(x not in (None, "") for x in row)
        }

    return {
        "previous_as_of": str(old[0].as_of),
        "current_as_of": str(new[0].as_of),
        "added_codes": sorted(new_map.keys() - old_map.keys()),
        "removed_codes": sorted(old_map.keys() - new_map.keys()),
        "changed_positions": changed,
        "account_values_changed": previous.get("account", {}).get("values", [])
        != current.get("account", {}).get("values", []),
        "account_labels_changed": account_labels(previous) != account_labels(current),
        "previous_total_cny": old_total,
        "current_total_cny": new_total,
        "market_value_difference_cny": new_total - old_total,
        "interpretation": "Snapshot value difference is not P&L, cash flow or executed turnover; transactions are unknown",
    }


def update_snapshot(root, bundle, config=None, catalog="private/acquisition.json", online_market=False):
    from .refresh import refresh_once

    root = root.resolve()
    with update_guard(root):
        config_path, previous_path = select_inputs(root, config=config)
        batch = root / "private/updates" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        batch.mkdir(parents=True)
        snapshot_path, new_config = batch / "snapshot.json", batch / "research.json"
        write_json(snapshot_path, bundle)
        status = {
            "started_at": datetime.now(UTC).isoformat(),
            "batch": batch.relative_to(root).as_posix(),
            "previous_snapshot": previous_path,
            "online_market": online_market,
        }
        protected = [
            root / ("private/" + name)
            for name in [
                "latest.json",
                "active_research.json",
                "market_catalog.json",
                "market_proxies.json",
                "holdings.json",
                "disclosure_qa.json",
                "derivatives.json",
                "normalization_manifest.json",
            ]
        ]
        backups = {p: p.read_bytes() if p.exists() else None for p in protected}
        try:
            changes = snapshot_changes(read_json(root / previous_path), bundle)
            as_of = changes["current_as_of"]
            if as_of < changes["previous_as_of"]:
                raise DataError(
                    "Snapshot update cannot regress research date; use explicit historical run/replay"
                )
            if as_of > datetime.now().astimezone().date().isoformat():
                raise DataError("Snapshot date is in the future")
            cfg = read_json(root / config_path)
            cfg["as_of"] = as_of
            ResearchConfig.model_validate(cfg)
            write_json(new_config, cfg)
            changes["previous_snapshot"] = previous_path
            changes["previous_config"] = config_path
            changes_path = snapshot_path.with_suffix(".changes.json")
            write_json(changes_path, changes)
            report = refresh_once(
                root,
                catalog,
                new_config.relative_to(root).as_posix(),
                snapshot_path.relative_to(root).as_posix(),
                online_market,
                _locked=True,
            )
            latest = read_json(root / "private/latest.json")
            write_json(
                root / "private/active_research.json",
                {
                    "snapshot": snapshot_path.relative_to(root).as_posix(),
                    "config": new_config.relative_to(root).as_posix(),
                    "run_id": latest["run_id"],
                },
            )
            status.update(
                status="SUCCESS_WITH_LIMITS",
                run_id=latest["run_id"],
                report=report,
                research_as_of=as_of,
                changes=changes,
            )
        except Exception as exc:
            for path, payload in backups.items():
                if payload is None:
                    path.unlink(missing_ok=True)
                else:
                    write_bytes_atomic(path, payload)
            status.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            status["finished_at"] = datetime.now(UTC).isoformat()
            write_json(batch / "status.json", status)
            write_json(root / "private/snapshot_update_status.json", status)
            write_json(root / "private/update_status.json", {"mode": "SSOT snapshot adoption", **status})
            with (root / "private/snapshot_update_history.jsonl").open("a", encoding="utf8") as handle:
                handle.write(json.dumps(status, ensure_ascii=False) + "\n")
        return status
