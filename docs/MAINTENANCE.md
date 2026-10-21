# Maintain the public release

## Regenerate synthetic screenshots

Use Python 3.12 and the recorded runtime constraints. The optional `preview` extra installs the renderer separately from the research runtime.

```sh
python -m pip install -c requirements.lock -e '.[dev,preview]'
python -m playwright install --with-deps chromium
python scripts/render_demo.py --workspace new-synthetic-workspace --output docs/demo
```

The workspace must not exist. The script creates the production synthetic demo, checks its `data_kind`, and renders its HTML with network requests blocked. On Linux, install a Chinese font such as `fonts-noto-cjk` before rendering. Review both images for legible Chinese text and the synthetic-data label before committing them.

## Publish a version

1. Update `project.version` in `pyproject.toml` and add the matching section in `CHANGELOG.md`.
2. Merge the release changes into `main` after the quality checks pass.
3. The `release` workflow waits for the successful `quality` workflow on that exact `main` commit. It downloads the Linux/Python 3.12 build from that run and verifies its asset checksums.
4. If the version tag has no release, the workflow creates it at the tested commit and publishes the wheel, source distribution, synthetic report bundle, standalone HTML, and `SHA256SUMS`.

The workflow runs only for successful pushes to this repository's `main` branch. It does not publish pull-request artifacts. It leaves an existing tag or release unchanged. A new version requires a new changelog section. PyPI publishing is not configured.

The report bundle contains output files, including CSVs and a manifest. It does not contain the evidence object store. Recreate a full demo workspace with the CLI to verify inputs and replay a run.

## Update dependencies

Dependabot checks Python requirements and GitHub Actions weekly. Review its changes; automatic merging is not enabled. Update the constraints in `requirements.lock` with any matching `pyproject.toml` change, and run the full quality workflow. The lock file is the recorded runtime and development snapshot, not a claim that every declared compatible version has been tested.

Python 3.12 and 3.13 run on Linux and Windows. Wheel installation, synthetic demo execution, manifest verification, and replay run outside the source checkout on each matrix entry.

`scikit-learn` is required by `portfolio_lab.risk.covariance`, which uses `sklearn.covariance.LedoitWolf`. Keep that dependency unless the estimator is deliberately replaced and its numerical behavior is revalidated.

## Export public source

```sh
python scripts/check_public_tree.py
python scripts/export_public.py --destination new-public-export
```

The export uses explicit text and image lists. Add public documentation or screenshots to that list deliberately. Keep account inputs, provider downloads, and runtime evidence outside the public tree. The committed PNGs must be reviewed synthetic report captures.

Check [source permissions](DATA_SOURCES.md) before enabling any live adapter. Public CI and release generation use the synthetic fixture only.
