"""Render documentation screenshots from a newly generated synthetic workspace."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="New, nonexistent demo directory")
    parser.add_argument("--output", type=Path, default=Path("docs/demo"))
    args = parser.parse_args()
    if args.workspace.exists():
        parser.error("The workspace must not exist; screenshots use only a new synthetic demo")
    subprocess.run(
        [sys.executable, "-m", "portfolio_lab.cli", "demo", "--destination", str(args.workspace)],
        check=True,
    )
    latest = json.loads((args.workspace / "private/latest.json").read_text(encoding="utf8"))
    run = args.workspace / "private/runs" / latest["run_id"]
    decision = json.loads((run / "decision.json").read_text(encoding="utf8"))
    if decision["data_kind"] != "synthetic":
        raise ValueError("Documentation screenshots require synthetic data")
    from playwright.sync_api import sync_playwright

    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.route("**/*", lambda route: route.abort())
        page.set_content((run / "Portfolio_Decision_Report.html").read_text(encoding="utf8"))
        page.get_by_text("SYNTHETIC DEMONSTRATION", exact=False).wait_for()
        page.screenshot(path=str(args.output / "report-overview.png"))
        heading = page.get_by_role("heading", name="权重与仓位作用", exact=True)
        page.locator("section").filter(has=heading).screenshot(path=str(args.output / "report-weights.png"))
        browser.close()
    print(f"Synthetic report screenshots: {args.output}")


if __name__ == "__main__":
    main()
