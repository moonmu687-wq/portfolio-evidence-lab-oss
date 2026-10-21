"""Rebuild normalized holdings from a versioned acquisition catalog, entirely offline."""

import re

from .evidence import DataError, input_manifest, read_json, write_json
from .filings import canonical_security, parse_full_equity_text
from .models import Holding
from .providers import holding_file, wind_tables


def normalize(root, catalog_path):
    catalog = read_json(catalog_path)
    holdings, qa, gaps, paths, sectors, fund_tables, gold_tables = [], [], [], [catalog_path], [], [], []
    for source in catalog["sources"]:
        path = root / source["path"]
        paths.append(path)
        paths.extend(root / p for p in source.get("evidence_paths", []))
        try:
            if source["adapter"] == "wind_top10":
                rows = holding_file(path, source["fund"], source["holding_date"])
                for h in rows:
                    alias = catalog.get("aliases", {}).get(h.security)
                    if alias:
                        if h.name != alias["name"]:
                            raise DataError("Alias security name mismatch")
                        h.security = alias["security"]
                    else:
                        h.security = canonical_security(h.security)
            elif source["adapter"] == "issuer_equity_pdf":
                from pypdf import PdfReader

                # Text is derived afresh from the PDF and therefore never trusted as an input.
                text = "\n".join(
                    f"PAGE {i + 1}\n" + p.extract_text() for i, p in enumerate(PdfReader(path).pages)
                )
                derived = root / "private/derived" / path.with_suffix(".txt").name
                derived.parent.mkdir(parents=True, exist_ok=True)
                derived.write_text(text, "utf8")
                rows, check = parse_full_equity_text(
                    derived,
                    source["fund"],
                    source["equity_total"],
                    source["pages"],
                    source["holding_date"],
                    source["published_date"],
                    source["report_title"],
                    source["layout"],
                )
                check.update(
                    url=source["url"],
                    holding_date=source["holding_date"],
                    published_date=source["published_date"],
                )
                qa.append(check)
                sectors.extend(parse_sector_totals(text, source, check["net_assets"]))
            elif source["adapter"] == "issuer_gold_pdf":
                from pypdf import PdfReader

                from .asset_tables import parse_physical_gold

                text = "\n".join(p.extract_text() for p in PdfReader(path).pages)
                rows, check = parse_physical_gold(text, source)
                gold_tables.append(check)
            elif source["adapter"] == "issuer_fund_top10_pdf":
                from pypdf import PdfReader

                from .fund_tables import parse_fund_investments

                text = "\n".join(
                    f"PAGE {i + 1}\n" + p.extract_text() for i, p in enumerate(PdfReader(path).pages)
                )
                rows, check = parse_fund_investments(text, source)
                fund_tables.append(check)
            elif source["adapter"] == "wind_feeder":
                rows = []
                for table in wind_tables(path):
                    names = [c["name"] for c in table["columns"]]
                    fields = source["fields"]
                    if not set(fields.values()).issubset(names):
                        gaps.append(path.name + ": ignored supplemental table outside declared feeder schema")
                        continue
                    indices = {k: names.index(v) for k, v in fields.items()}
                    if table["columns"][indices["weight"]].get("unit") != "%":
                        raise DataError("Feeder percentage unit missing")
                    for row in table["rows"]:
                        if str(row[indices["fund"]]).split(".")[0] != source["fund"]:
                            raise DataError("Wrong feeder identity")
                        sec = str(row[indices["security"]])
                        sec = source.get("security_prefix", "") + sec
                        rows.append(
                            Holding(
                                fund=source["fund"],
                                security=sec,
                                name=row[indices["name"]],
                                weight=row[indices["weight"]] / 100,
                                holding_date=source["holding_date"],
                                source_id=path.name,
                                scope="feeder",
                                kind="fund",
                            )
                        )
                if not rows:
                    raise DataError("No rows match declared feeder schema")
            else:
                raise DataError("Unsupported adapter: " + source["adapter"])
            holdings.extend(rows)
        except (DataError, ValueError) as exc:
            if source.get("required", True):
                raise DataError(f"{path.name}: {exc}") from exc
            gaps.append(str(exc))
    classes = {}
    descriptive_names = {h.security: h.name for h in holdings if h.name != h.security.split(":")[-1]}
    for h in holdings:
        if h.name == h.security.split(":")[-1] and h.security in descriptive_names:
            h.name = descriptive_names[h.security]
    expected_names = {}
    for h in holdings:
        expected_names.setdefault(h.security, set()).add(h.name.replace(" ", ""))
    for relative in catalog.get("classifications", []):
        path = root / relative
        paths.append(path)
        for table in wind_tables(path):
            names = [c["name"] for c in table["columns"]]
            if "Wind代码" not in names:
                gaps.append(f"{path.name}: classification table lacks stable security identifier")
                continue
            fields = {}
            for attr, match in [
                ("sector", lambda n: "一级行业" in n and "." not in n),
                ("currency", lambda n: n == "交易币种"),
                ("region", lambda n: n == "注册地所在国家或地区"),
            ]:
                idx = [i for i, n in enumerate(names) if match(n)]
                if len(idx) == 1:
                    fields[attr] = idx[0]
            for row in table["rows"]:
                try:
                    sec = canonical_security(row[names.index("Wind代码")])
                except (DataError, AttributeError):
                    continue
                if sec not in expected_names:
                    continue
                if sec.startswith(("CN:", "HK:")) and (
                    "证券简称" not in names
                    or str(row[names.index("证券简称")]).replace(" ", "") not in expected_names[sec]
                ):
                    gaps.append(
                        f"{path.name}: {sec} classification name does not match disclosed holding; excluded"
                    )
                    continue
                entry = classes.setdefault(sec, {})
                for k, i in fields.items():
                    if row[i]:
                        if k in entry and entry[k] != row[i]:
                            raise DataError(f"Conflicting classification {sec}/{k}")
                        entry[k] = row[i]
                entry["classification_source"] = (
                    path.name + "; observed " + catalog["classification_observed_at"]
                )
    for h in holdings:
        for k, v in classes.get(h.security, {}).items():
            setattr(h, k, v)
    from .derivatives import parse_single_future

    derivatives = []
    for spec in catalog.get("derivatives", []):
        from pypdf import PdfReader

        path = root / spec["path"]
        paths.append(path)
        text = "\n".join(f"PAGE {i + 1}\n" + p.extract_text() for i, p in enumerate(PdfReader(path).pages))
        derivatives.append(parse_single_future(text, spec))
    write_json(root / "private/derivatives.json", derivatives)
    write_json(root / "private/holdings.json", [h.model_dump(mode="json") for h in holdings])
    write_json(
        root / "private/disclosure_qa.json",
        {
            "full_equity": qa,
            "gaps": sorted(set(gaps)),
            "industry_totals": sectors,
            "fund_investments": fund_tables,
            "gold_assets": gold_tables,
        },
    )
    write_json(
        root / "private/normalization_manifest.json",
        {
            "inputs": input_manifest(paths, root),
            "outputs": input_manifest(
                [
                    root / "private/holdings.json",
                    root / "private/disclosure_qa.json",
                    root / "private/derivatives.json",
                ],
                root,
            ),
        },
    )
    return len(holdings)


def parse_sector_totals(text, source, nav):
    """Keep the original taxonomies separate. Never infer a stock's industry from its fund."""
    ranked = source["layout"] in {"de_ranked", "hk_ranked"}
    if ranked:
        body = text[text.rfind("§7") :]
        heading = re.search(r"期末(?:指数投资)?按行业分类的(?:权益|港股通投资股票)投资组合", body)
        end = re.search(r"所有(?:权益|股票)投资\s*明细", body)
        if not heading or not end:
            raise DataError("Ranked report industry table boundaries absent")
        text = body[heading.end() : end.start()]
        if "GICS" not in text:
            raise DataError("Ranked report GICS classification unverified")
    heading = (
        "期末按行业分类的权益投资组合"
        if source["layout"] in {"us", "global"}
        else "报告期末按行业分类的境内股票投资组合"
    )
    start = text.rfind(heading)
    end = text.find("所有权益投资明细" if source["layout"] in {"us", "global"} else "所有股票投资明细", start)
    if not ranked and (start < 0 or end < 0):
        return []
    section = text if ranked else text[start:end]
    # A wrapped CSRC label must stay attached to its letter code. Otherwise the
    # trailing line (for example just "业") can reconcile numerically while
    # silently losing its meaning.
    section = re.sub(
        r"^([A-S][ \t]+[^\d\n-]+)\n([ \t]*[\u4e00-\u9fff][^\d\n-]*?)(?=[\d,]+\.\d{2}[ \t]+\d+\.\d{2})",
        lambda m: m[1].rstrip() + m[2],
        section,
        flags=re.MULTILINE,
    )
    # Aggregate table rows have exactly amount and percentage after a label.
    pattern = r"^(?:(?:[A-S]|\d{2}) )?([^\d\n]+?)\s+([\d,]+\.\d{2})\s+(\d+\.\d{2})\s*$"
    result = []
    hk_marker = section.find("港股通投资股票投资组合")
    for m in re.finditer(pattern, section, re.MULTILINE):
        label = m[1].strip()
        if label == "合计":
            continue
        if len(label) < 2:
            raise DataError("Truncated industry label")
        value = float(m[2].replace(",", ""))
        weight = value / nav
        if abs(weight * 100 - float(m[3])) > 0.011:
            raise DataError("Sector denominator mismatch")
        taxonomy = (
            source.get("industry_taxonomy", "Bloomberg")
            if source["layout"] in {"us", "global"}
            else ("Bloomberg" if hk_marker >= 0 and m.start() > hk_marker else "CSRC")
        )
        if ranked:
            taxonomy = "GICS"
        if taxonomy == "CSRC":
            label = re.sub(r"\s+", "", label)
        if taxonomy == "GICS" and "GICS" not in section:
            raise DataError("GICS taxonomy not confirmed in report")
        result.append(
            {
                "fund": source["fund"],
                "taxonomy": taxonomy,
                "sector": label,
                "weight": weight,
                "holding_date": source["holding_date"],
                "source": source["path"],
            }
        )
    if result and abs(sum(x["weight"] for x in result) - source["equity_total"] / nav) > 1e-8:
        raise DataError("Industry totals do not reconcile to disclosed equity NAV share")
    # The index and active sleeves can share industry labels. Present the
    # fund-level sum while retaining the original taxonomy and source.
    combined = {}
    for row in result:
        key = (row["taxonomy"], row["sector"])
        if key in combined:
            combined[key]["weight"] += row["weight"]
        else:
            combined[key] = row.copy()
    return list(combined.values())
