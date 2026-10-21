"""Check intended public files only. Does not read credential stores."""

import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, text=True
).splitlines()
bad = []
for name in files:
    p = root / name
    if name.startswith(("private/", ".venv")) or name.endswith((".pem", ".key", ".env")):
        bad.append(name + ": private path")
        continue
    if not p.is_file():
        continue
    text = p.read_text("utf8", errors="replace")
    if re.search(
        r"ya29\.[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]{20,}",
        text,
    ):
        bad.append(name + ": sensitive pattern")
if bad:
    raise SystemExit("\n".join(bad))
print(f"Public tree scan passed: {len(files)} files; private evidence excluded")
