import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_public.py"
spec = importlib.util.spec_from_file_location("public_export", SCRIPT)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def test_export_omits_runtime_files_and_git_history(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    for name in exporter.ROOT_FILES | {
        "docs/DATA.md",
        "scripts/export_public.py",
        "scripts/check_public_tree.py",
    }:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("public fixture\n", encoding="utf8")
    for name in ["private/ssot/raw.json", ".git/config", "reports/account.html", "tests/test_real_replay.py"]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_SENTINEL", encoding="utf8")
    destination = tmp_path / "export"
    exporter.export_public(root, destination)
    assert not (destination / "private").exists()
    assert not (destination / ".git").exists()
    assert not (destination / "reports").exists()
    assert not (destination / "tests/test_real_replay.py").exists()
    assert all("PRIVATE_SENTINEL" not in p.read_text("utf8") for p in destination.rglob("*") if p.is_file())
    (root / "README.md").write_text("sk-" + "x" * 30, encoding="utf8")
    with pytest.raises(ValueError, match="credential"):
        exporter.export_public(root, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()
