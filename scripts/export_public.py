"""Export a reviewed source whitelist, without account data or repository history."""

import argparse
import re
import shutil
from pathlib import Path

ROOT_FILES = {
    "CHANGELOG.md",
    "README.md",
    "README.zh-CN.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "requirements.lock",
    "MANIFEST.in",
    ".gitignore",
    ".gitattributes",
}
DOC_FILES = {
    "docs/DATA.md",
    "docs/DATA_SOURCES.md",
    "docs/MAINTENANCE.md",
    "docs/demo/README.md",
}
PREVIEW_IMAGES = {"docs/demo/report-overview.png", "docs/demo/report-weights.png"}
RULES = {
    "credential": r"(?:sk-[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})",
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "account sheet": r"docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]{20,}",
    "absolute home path": (
        r"(?<![A-Za-z0-9:/.])(?:[A-Za-z]:[\\/]Users[\\/][^\\/\s]+|"
        + "/"
        + r"(?:home|Users)/[^/\s]+)"
    ),
}


def selected(root):
    files = [root / name for name in sorted(ROOT_FILES)]
    files += sorted((root / "src/portfolio_lab").glob("*.py"))
    files += sorted(p for p in (root / "tests").glob("test_*.py") if p.name != "test_real_replay.py")
    files += [root / name for name in sorted(DOC_FILES | PREVIEW_IMAGES)]
    files += [
        root / name
        for name in ("scripts/export_public.py", "scripts/check_public_tree.py", "scripts/render_demo.py")
    ]
    files += [root / ".github/dependabot.yml"]
    files += sorted((root / ".github/workflows").glob("*.yml"))
    return files


def export_public(root, destination):
    root, destination = root.resolve(), destination.resolve()
    if destination.exists() or root == destination or root.is_relative_to(destination):
        raise ValueError("Export destination must be a new directory outside the source's ancestors")
    files = selected(root)
    for source in files:
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Missing or linked public source: {source.relative_to(root)}")
        if source.relative_to(root).as_posix() in PREVIEW_IMAGES:
            if not source.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Invalid preview PNG: {source.relative_to(root)}")
            continue
        body = source.read_text(encoding="utf8")
        for label, pattern in RULES.items():
            if re.search(pattern, body):
                raise ValueError(f"Review required: {source.relative_to(root)}: {label}")
    destination.mkdir(parents=True)
    for source in files:
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        count = export_public(Path(__file__).resolve().parents[1], args.destination)
    except ValueError as exc:
        parser.exit(2, str(exc) + "\n")
    print(f"Exported {count} source files; no Git history or runtime evidence")
