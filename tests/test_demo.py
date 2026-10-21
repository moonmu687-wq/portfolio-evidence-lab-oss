import subprocess
import sys

import pytest

from portfolio_lab.demo import create_demo, run_demo
from portfolio_lab.evidence import DataError, read_json, verify_manifest


def test_offline_demo_reconciles_known_exposures_and_replays(tmp_path, monkeypatch):
    def forbidden_network(*args, **kwargs):
        raise AssertionError("Offline demo attempted network access")

    monkeypatch.setattr("requests.sessions.Session.request", forbidden_network)
    root = tmp_path / "demo"
    out, result = run_demo(root)
    assert result["data_kind"] == "synthetic"
    current = result["candidates"]["Current"]
    assert current["exposure"]["resolved_nav_fraction"] == pytest.approx(0.719)
    assert current["exposure"]["security_exposure"]["US:SYNTH_A"] == pytest.approx(0.3115)
    assert sum(current["exposure"]["security_exposure"].values()) == pytest.approx(1)
    assert sum(x["component_vol"] for x in current["risk_contributions"].values()) == pytest.approx(
        current["metrics"]["annual_volatility"]
    )
    html = (out / "Portfolio_Decision_Report.html").read_text("utf8")
    assert "SYNTHETIC DEMONSTRATION" in html
    assert "Deterministic synthetic fixture" in html
    manifest_path = out / "manifest.json"
    manifest = read_json(manifest_path)
    for field in ["inputs", "outputs", "code"]:
        verify_manifest(manifest[field], root)
    replay = subprocess.run(
        [
            sys.executable,
            "-m",
            "portfolio_lab.cli",
            "replay",
            str(manifest_path),
            "--root",
            str(root),
            "--destination",
            str(tmp_path / "replay"),
        ],
        capture_output=True,
        text=True,
    )
    assert replay.returncode == 0, replay.stderr + replay.stdout
    assert "Historical replay reproduced" in replay.stdout
    (root / "private/nav.csv").write_text("tampered", encoding="utf8")
    with pytest.raises(DataError, match="Evidence changed"):
        verify_manifest(manifest["inputs"], root)


def test_demo_never_overwrites_an_existing_directory(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep", encoding="utf8")
    with pytest.raises(DataError, match="must not exist"):
        create_demo(destination)
    assert sentinel.read_text("utf8") == "keep"
