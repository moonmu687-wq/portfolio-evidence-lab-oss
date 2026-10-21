"""Self-contained report generated only from deterministic calculation output."""

from html import escape
from pathlib import Path


def pct(x):
    return "N/A" if x is None else f"{x:.2%}"


def number(x):
    return "N/A" if x is None else f"{x:,.2f}"


def table(headers, rows):
    return (
        '<div class="scroll"><table><thead><tr>'
        + "".join("<th>" + escape(str(h)) + "</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join("<td>" + escape(str(v)) + "</td>" for v in row) + "</tr>" for row in rows)
        + "</tbody></table></div>"
    )


def render_report(r, path: Path):
    candidates = r["candidates"]
    current = candidates["Current"]
    best = candidates["Minimum variance"]
    risk = current["metrics"]["annual_volatility"]
    coverage = current["exposure"]["resolved_nav_fraction"]
    names = {p["code"]: p["name"] for p in r["positions"]}
    active_constraints = {
        k: v
        for k, v in r["configuration"]["constraints"].items()
        if k != "groups" and v is not None and v != {}
    }
    constraints_text = (
        "本轮未加入个人风险偏好限制。"
        if not active_constraints
        else "本轮使用配置中明确列出的约束；详见 decision.json。"
    )
    parts = []
    if r.get("data_kind") == "synthetic":
        parts.append(
            '<section class="notice"><b>SYNTHETIC DEMONSTRATION · 合成数据演示</b>'
            "<p>全部产品、持仓、金额和净值均为虚构，仅用于复现计算流程。</p></section>"
        )
    parts.append(f"""<header><div class="eyebrow">PORTFOLIO EVIDENCE LAB · 基金组合研究</div>
    <h1>Portfolio Decision Report</h1><p>持仓快照 {escape(r["as_of"])} · 人民币基金净值口径 · 可复现运行 {r["run_id"]}</p>
    <div class="badge">研究候选 · 尚非可执行交易方案</div></header>
    <section class="kpis"><article><span>输入持仓市值</span><b>¥{number(r["position_total_cny"])}</b><small>{r["position_count"]} 个基金 / ETF / LOF</small></article>
    <article><span>当前组合年化波动估计</span><b>{pct(risk)}</b><small>Ledoit–Wolf · {r["alignment"]["periods"]} 个共同周收益</small></article>
    <article><span>已识别底层资产占净值</span><b>{pct(coverage)}</b><small>含股票及已核验黄金；其余保留未知</small></article></section>""")
    update = r.get("snapshot_update")
    if update:
        parts.append(
            "<section><h2>本次源表更新</h2>"
            + f"<p>实际持仓日期：{escape(update['previous_as_of'])} → {escape(update['current_as_of'])}；"
            + f"源表读取时间：{escape(update.get('source_retrieved_at') or '未记录')}。</p>"
            + table(
                ["新增产品", "移除产品", "字段变化的产品", "市值差额（元）"],
                [
                    [
                        ", ".join(update["added_codes"]) or "无",
                        ", ".join(update["removed_codes"]) or "无",
                        ", ".join(x["code"] for x in update["changed_positions"]) or "无",
                        number(update["market_value_difference_cny"]),
                    ]
                ],
            )
            + "<p>市值差额不等于投资收益、出入金或成交金额；没有交易流水时不推断这些原因。"
            + "读取时间不替代持仓日期，空白约束保持空白。逐字段变化保留于本次更新的变更记录及 decision.json。</p></section>"
        )
    parts.append(
        "<section><h2>本轮能支持的决策</h2>"
        + f"""
    <p>当前组合在同一估计方法下的波动率为 <strong>{pct(risk)}</strong>。现有产品范围内，最低方差候选为
    <strong>{pct(best["metrics"]["annual_volatility"])}</strong>，需要单边换手 <strong>{pct(best["cost"]["one_way_turnover"])}</strong>。
    这说明现有产品之间有调整风险结构的空间；它不证明该候选未来收益更好。</p>
    <p>{constraints_text}所有候选的共同建模范围是现有产品、只做多、总权重 100%；这些是研究口径。
    如允许无收益目标的理想现金，最低波动模型会退化为全部现金，因此现金情景单独列示。
    产品配置保留单项上下限、分组上限、换手和波动目标。</p>
    <p class="notice">底层持仓日期为 {" / ".join(r["disclosure_dates"])}，不能视作账户快照日实际底层仓位；风险数据以 {r["alignment"]["end"]} 为共同周末。
    ETF / LOF 的场内溢折价和交易冲击未纳入净值风险。实际费率、份额、持有天数和申赎规则仍需补齐。</p></section>"""
    )
    leaders = sorted(r["positions"], key=lambda p: -p["risk_share"])[:2]
    largest = max(best["weights"], key=best["weights"].get)
    marginal = sorted(r["leave_one_out"], key=lambda x: -x["increase_vs_all_available"])[:3]
    parts.append(
        "<section><h2>值得复核的仓位判断</h2>"
        + f"""
    <p><strong>{"、".join(p["code"] for p in leaders)}</strong> 合计占资金 {pct(sum(p["weight"] for p in leaders))}，
    却承担 {pct(sum(p["risk_share"] for p in leaders))} 的波动贡献。优先研究这些仓位的变动，比只清理金额很小的产品更能改变本模型下的风险。</p>
    <p>最低方差候选最大单项为 {largest} {escape(names[largest])}，权重 {pct(best["weights"][largest])}，
    底层资产已识别比例从当前 {pct(coverage)} 变为 {pct(best["exposure"]["resolved_nav_fraction"])}。
    风险目标改变了持仓结构，也引入了集中度与透明度的取舍；不能仅因波动较低就采用。</p>
    <p>逐个禁止持有再重新优化，{"、".join(x["code"] for x in marginal)} 对最低方差边界的影响最大。
    因此“证券重叠高”与“没有边际作用”不是同一个结论。此处只检验波动边界，不评估未来收益价值。</p></section>"""
    )
    rows = []
    for label, c in candidates.items():
        m = c["metrics"]
        cost50 = next(
            (s["cost_cny"] for s in c["cost"]["sensitivity"] if s["all_in_bps_per_traded_notional"] == 50),
            None,
        )
        rows.append(
            [
                label,
                pct(m["annual_volatility"]),
                pct(m["sample_annual_volatility"]),
                pct(m["observed_endpoint_rebalanced_max_drawdown"]),
                pct(m["weekly_cvar95"]["cvar"]),
                pct(c["cost"]["one_way_turnover"]),
                number(cost50),
                pct(c["exposure"]["resolved_nav_fraction"]),
            ]
        )
    parts.append(
        "<section><h2>Current vs Candidate</h2><p>同一产品集合、同一收益窗口。回撤来自完整可观测端点路径；协方差仅使用完整同频周收益。</p>"
        + table(
            [
                "组合",
                "年化波动·收缩估计",
                "年化波动·样本",
                "历史最大回撤",
                "周 CVaR95*",
                "单边换手",
                "50bps情景成本/元",
                "底层资产覆盖率",
            ],
            rows,
        )
        + '<p class="small">* CVaR95 的尾部只有约 '
        + number(current["metrics"]["weekly_cvar95"]["tail_equivalent_observations"])
        + " 个等效观测，属于不稳定的描述性估计；未将周 CVaR 乘根号年化。Historical-return stress 使用历史均值，不是收益预测或优先候选。</p></section>"
    )
    labels = list(candidates)
    parts.append(
        "<section><h2>权重与仓位作用</h2>"
        + table(
            ["代码 / 产品"] + labels,
            [
                [p["code"] + " " + p["name"]]
                + [pct(candidates[label]["weights"][p["code"]]) for label in labels]
                for p in r["positions"]
            ],
        )
    )
    parts.append(
        table(
            ["产品", "当前资金权重", "波动风险贡献份额", "增加1个百分点的年化波动变化", "已识别底层资产比例"],
            [
                [
                    p["code"] + " " + p["name"],
                    pct(p["weight"]),
                    pct(p["risk_share"]),
                    pct(p["funded_plus_1pp_vol_delta"]),
                    pct(p["identified_nav_fraction"]),
                ]
                for p in r["positions"]
            ],
        )
    )
    parts.append("""<p class="small">增加 1 个百分点由其余仓位按比例减仓融资；这是协方差模型的局部情景。
    风险贡献是基金净值层面的 Euler 波动贡献，不能冒充底层证券收益归因。用户持有理由为空时保持未知。</p></section>""")
    rows = []
    for label, c in candidates.items():
        h = c["holdout"]
        m = h["metrics"]
        ci = c["bootstrap"]["annual_vol_difference_95_interval"]
        rows.append(
            [
                label,
                pct(m["sample_annual_volatility"]),
                pct(m["observed_period_compound_return"]),
                pct(m["observed_endpoint_rebalanced_max_drawdown"]),
                pct(h["cost"]["one_way_turnover"]),
                pct(ci[0]) + " 至 " + pct(ci[1]),
            ]
        )
    hold = current["holdout"]
    parts.append(
        "<section><h2>时间留出检验与不确定性</h2>"
        + f"<p>先使用截至 {hold['train_end']} 的收益求权重，再检验 {hold['test_start']} 至 {hold['test_end']}，共 {hold['test_observations']} 个共同周收益。检验权重与上表基于全样本的候选权重不同。</p>"
        + table(
            [
                "组合",
                "留出期年化波动·样本",
                "留出期反事实收益·毛",
                "留出期回撤",
                "初始换手",
                "全样本波动差95%重抽样区间",
            ],
            rows,
        )
        + """<p class="notice">这只是一次时间留出；当前产品集合和当前基准权重是事后给定，不能据此声称可投资策略回测或显著超额收益。
        重抽样固定已拟合的权重，仍有选择偏差。净收益必须另扣初始及后续再平衡费用，表内毛收益未扣。</p></section>"""
    )
    parts.append(
        "<section><h2>底层重叠：已知下限与未识别部分</h2>"
        + table(
            ["产品 A", "产品 B", "证券重叠下限", "保守上界", "净值收益相关系数"],
            [
                [
                    x["a"] + " " + names[x["a"]],
                    x["b"] + " " + names[x["b"]],
                    pct(x["overlap_lower"]),
                    pct(x["overlap_upper_conservative"]),
                    f"{x['correlation']:.3f}",
                ]
                for x in r["overlap"][:15]
            ],
        )
        + """<p>重叠下限为已披露相同证券权重的逐项较小值之和。未知部分不等于零重叠。
        A/H 股及同一公司的不同股份类别在证券层保留不同身份；未验证的发行人归并不自动执行。</p></section>"""
    )
    low_equity_overlap = sorted(
        [x for x in r.get("complete_equity_overlap", []) if x["equity_overlap_nav_fraction"] < 0.05],
        key=lambda x: -x["return_correlation"],
    )[:8]
    if low_equity_overlap:
        parts.append(
            "<section><h2>股票不同，风险仍可能相近</h2>"
            "<p>两只基金都有同日完整股票表时，可以确定该日直接股票的重叠。下表选取股票重叠低于 5% 的配对，按净值收益相关性排序展示前八组；全部结果见 complete_equity_overlap.csv。</p>"
            + table(
                ["产品 A", "产品 B", "持仓日期", "相同证券数量", "直接股票重叠/净值", "收益相关系数"],
                [
                    [
                        x["a"],
                        x["b"],
                        x["holding_date"],
                        x["shared_security_count"],
                        "<0.01%"
                        if 0 < x["equity_overlap_nav_fraction"] < 0.0001
                        else pct(x["equity_overlap_nav_fraction"]),
                        f"{x['return_correlation']:.3f}",
                    ]
                    for x in low_equity_overlap
                ],
            )
            + "<p>未将股票权重重新放大至 100%。零股票重叠只说明披露日未持有相同上市证券，不证明风险独立；产业链、市场因子、不同股份类别、衍生品和非股票资产仍可能形成共同风险。收益相关性来自整个估计窗口，不能归因于单个披露日的股票表。</p></section>"
        )
    exposures = current["exposure"]
    known = [
        (k, v)
        for k, v in exposures["security_exposure"].items()
        if not k.startswith(("UNKNOWN:", "UNRESOLVED_FUND:"))
    ]
    parts.append(
        "<section><h2>当前组合的已识别暴露</h2>"
        + table(
            ["底层资产", "名称", "占组合净值"],
            [[k, r["security_registry"][k]["name"], pct(v)] for k, v in known[:25]],
        )
    )
    for dim, title in [
        ("listing_market", "证券上市市场"),
        ("sector", "Wind 一级行业"),
        ("region", "注册国家 / 地区"),
        ("currency", "证券交易币种"),
    ]:
        parts.append(
            "<h3>"
            + title
            + "</h3>"
            + table(["分类", "组合净值比例"], [[k, pct(v)] for k, v in exposures["dimensions"][dim].items()])
        )
    factors = r["statistical_factors"]
    parts.append(
        "<p>行业及公司属性使用当前分类快照，可能与持仓报告时点不同。交易币种不是净外汇敞口；注册地不是收入来源。</p>"
        + f"<p>统计主成分前三项解释产品收益方差的比例为 {' / '.join(pct(x) for x in factors['explained_variance_ratio'])}。它们没有被命名为经济因子；价值、规模等纯风格 beta 仍为空。</p></section>"
    )
    market = r.get("market_proxy_model")
    if market:
        proxy_names = list(market["source_qa"])

        def beta_cell(model, name):
            b = model["betas"][name]
            lo, hi = b["ci95_normal"]
            return f"{b['estimate']:.2f} [{lo:.2f}, {hi:.2f}]"

        parts.append(
            "<section><h2>市场敏感度：人民币基金代理模型</h2>"
            + "<p>模型结果：将同频组合周收益同时对三个市场代理回归。系数表示其他代理不变时，该代理收益变化 1 个百分点对应的组合收益变化百分点；这是样本关联，不是持仓比例或因果预测。括号为近似 95% HAC 区间。</p>"
            + table(
                ["代理", "基金代码", "独立核对日数", "最大收益差"],
                [
                    [v["label"], v["code"], v["matched_dates"], f"{v['maximum_return_difference']:.2e}"]
                    for v in market["source_qa"].values()
                ],
            )
            + f"<p>共同样本：{len(market['dates'])} 周，{market['dates'][0]} 至 {market['dates'][-1]}。采用带截距 OLS、3 个日历周滞后的 Newey-West 标准误；缺失周不填补，也不压缩为相邻周。</p>"
            + table(
                ["组合"]
                + [market["source_qa"][n]["label"] + " β [区间]" for n in proxy_names]
                + ["样本解释比例 R²", "未解释方差", "留出期拟合 R²"],
                [
                    [label]
                    + [beta_cell(m, n) for n in proxy_names]
                    + [
                        pct(m["r_squared"]),
                        pct(m["residual_variance_fraction"]),
                        pct(m["holdout"]["r_squared_vs_training_mean"]),
                    ]
                    for label, m in market["candidates"].items()
                ],
            )
            + "<p>留出期只检验较早估计的系数对后续同期市场变动的拟合；候选权重仍来自全样本，因此不是候选交易策略回测。R² 可以为负，表示比训练期均值基准更差。未解释部分不能直接称为独立风险。</p>"
            + "<details><summary>查看各产品市场敏感度</summary>"
            + table(
                ["产品"] + [market["source_qa"][n]["label"] + " β [区间]" for n in proxy_names] + ["R²"],
                [
                    [code] + [beta_cell(m, n) for n in proxy_names] + [pct(m["r_squared"])]
                    for code, m in market["products"].items()
                ],
            )
            + "</details>"
            + "<p>人民币美股及黄金基金代理含汇率、费用和跟踪影响；没有分别识别外汇、科技、价值、规模或动量。跨市场收盘不同步及短样本会影响结果。截距不称为 alpha。模型解释方差使用未收缩样本协方差，与优化器风险口径分开；不会改变候选权重或已核验穿透率。</p>"
            + "<p>沪深300基金三个现金分红事件已核对发行人原始公告，统一按除息日净值再投资计算；与官网累计收益曲线在分红日存在口径差异，原始差异保留。黄金份额折算来自数据商明示事件并与发行人累计收益核对，未取得该次折算原始公告。以上均非真实成交收益。</p></section>"
        )
    parts.append(
        "<section><h2>数据覆盖与原文核对</h2>"
        + table(
            ["基金", "完整股票明细行数", "股票金额合计/元", "占基金净值", "已核对页"],
            [
                [x["fund"], x["rows"], number(x["fair_value_sum"]), pct(x["equity_nav_coverage"]), x["pages"]]
                for x in r["disclosure_qa"].get("full_equity", [])
            ],
        )
        + "<p>完整股票明细 ≠ 完整基金资产。现金、应收应付、衍生品以及未穿透基金仍保留残余。披露滞后不会因为计算精确而消失。</p></section>"
    )
    for gold in r["disclosure_qa"].get("gold_assets", []):
        parts.append(
            "<section><h2>黄金联接的底层资产核对</h2>"
            + table(
                ["目标基金", "资产", "公允价值/元", "占目标基金净值", "折算当前组合净值"],
                [
                    [
                        gold["fund"],
                        gold["security"],
                        number(gold["fair_value_cny"]),
                        pct(gold["identified_nav_fraction"]),
                        pct(exposures["security_exposure"].get(gold["security"], 0)),
                    ]
                ],
            )
            + f'<p>披露日期 {escape(gold["holding_date"])}；<a href="{escape(gold["url"])}">原始报告第 {escape(gold["pages"])} 页</a>。'
            + "黄金明细金额与资产负债表贵金属总额核平；经联接基金权重逐层相乘，剩余净资产保持未知。人民币计价不等于消除了国际金价或汇率风险，黄金没有被归入股票行业。</p></section>"
        )
    for basket in r.get("supplemental_basket_estimates", []):
        parts.append(
            "<section><h2>海外第二层：单列估算，未计入核验覆盖率</h2>"
            + f"<p>{escape(basket['parent'])} → {escape(basket['fund'])}，两层持仓日均为 {escape(basket['holding_date'])}。"
            + "母基金持有比例来自中报净值口径；下层权重来自管理人官网投资账簿，采用供应商价格，可能与会计净值口径不同。"
            + "官网历史持仓首次公开日期未知，不能用于证明基准日当时可知的持仓，也未用于优化或风险计算。</p>"
            + table(
                ["组合", "该海外基金间接权重", "其中股票穿透估算"],
                [
                    [name, pct(w), pct(w * basket["equity_weight"])]
                    for name, w in basket["portfolio_fund_weights"].items()
                ],
            )
            + table(
                ["前十大下层证券", "下层官网权重", "Current 间接权重估算"],
                [
                    [
                        x["security"] + " · " + x["name"],
                        pct(x["basket_weight"]),
                        f"{x['estimated_portfolio_weights']['Current']:.4%}",
                    ]
                    for x in sorted(basket["equity_estimates"], key=lambda x: -x["basket_weight"])[:10]
                ],
            )
            + "<p>货币基金、保证金和期货保留原始类别；期货名义金额不计入股票权重。"
            + "全部行与各候选估算见 supplemental_basket_estimates.csv，原始分类及非股票行见 decision.json。"
            + "本节估算不改变主表覆盖率、证券重叠或协方差。"
            + f"<a href='{escape(basket['source_url'])}'>发行人来源</a>。</p></section>"
        )
    industry = r["disclosure_qa"].get("industry_totals", [])
    if industry:
        parts.append(
            "<section><h2>半年报行业汇总：保留原始分类体系</h2><p>这些是基金层面的真实披露，不能分配给未知证券；证监会、GICS 与彭博分类保留各自口径。</p>"
            + table(
                ["产品", "分类体系", "行业", "占该基金净值", "按当前权重折算组合净值"],
                [
                    [
                        x["fund"],
                        x["taxonomy"],
                        x["sector"],
                        pct(x["weight"]),
                        pct(x["weight"] * current["weights"][x["fund"]]),
                    ]
                    for x in industry
                ],
            )
            + "</section>"
        )
    for fund_table in r["disclosure_qa"].get("fund_investments", []):
        fund_weight = current["weights"].get(fund_table["fund"], 0)
        parts.append(
            f"<section><h2>基金中基金的第一层：{escape(fund_table['fund'])}</h2>"
            + f"<p>前十项基金投资占该基金净值 {pct(fund_table['disclosed_top10_nav_fraction'])}；"
            + f"另有 {pct(fund_table['other_fund_nav_fraction'])} 基金投资未逐项披露。"
            + "这些是基金份额，尚不能视作已穿透的股票或行业暴露。基金名称与主题也不直接转化为证券分类。</p>"
            + table(
                ["持有基金", "基金身份", "占母基金净值", "折算当前组合权重"],
                [
                    [x["name"], x["security"], pct(x["nav_fraction"]), pct(x["nav_fraction"] * fund_weight)]
                    for x in fund_table["rows"]
                ],
            )
            + f'<p>披露日期 {escape(fund_table["holding_date"])}；<a href="{escape(fund_table["url"], quote=True)}">'
            + f"原始报告第 {escape(fund_table['pages'])} 页</a>。净值分母采用全基金合并净资产，不能使用单一份额类别的规模。</p></section>"
        )
    derivative_rows = current["derivative_exposure"]["positions"]
    if derivative_rows:
        parts.append(
            "<section><h2>期货敞口：净公允价值为零仍可能承担市场风险</h2><p>以下按期末合约市值除以基金净值计算，并用报告名义金额加估值变动核对。它们不加入资产净值占比或股票覆盖率；基金净值历史已经包含期货影响，不再次叠加波动。</p>"
            + table(
                ["基金", "合约 / 标的", "合约市值/元", "占该基金净值", "按当前仓位折算组合敞口"],
                [
                    [
                        x["fund"],
                        x["contract"] + " / " + x["underlying"],
                        number(x["contract_market_value_cny"]),
                        pct(x["signed_notional_nav_fraction"]),
                        pct(x["portfolio_signed_notional_fraction"]),
                    ]
                    for x in derivative_rows
                ],
            )
            + table(
                ["组合", "已识别股指期货名义敞口"],
                [
                    [label, pct(c["derivative_exposure"]["sum_disclosed_long_notional_fraction"])]
                    for label, c in candidates.items()
                ],
            )
            + "<p>原文："
            + " · ".join(
                f'<a href="{escape(x["url"], quote=True)}">{escape(x["fund"])} 第 {escape(x["pages"])} 页</a>'
                for x in derivative_rows
            )
            + '</p><p class="notice">这里只覆盖已核对的合约，不代表其他产品没有衍生品。指数合约尚未展开至各期成分股；不要将净值残余直接视为无风险现金。</p></section>'
        )
    official = r.get("issuer_nav_cross_validation", {})
    if official:
        parts.append(
            "<section><h2>净值来源与交叉核对</h2><p>官方累计收益与公开第三方净值使用各自的解析规则；均与已保存的 Wind 人民币复权净值按共同日期核对收益。第三方数据不冒充管理人原始披露。网页四舍五入涨跌幅不参与收益计算；超出容差时停止。</p>"
            + table(
                ["产品", "来源", "共同日期数", "最大单期收益差/bps", "参考核验截止", "最新源数据"],
                [
                    [
                        code,
                        qa.get("provider", "基金管理人官网"),
                        qa["matched_dates"],
                        f"{qa['maximum_return_difference'] * 10000:.8f}",
                        qa.get("reference_last_date", "见输入清单"),
                        qa.get("last_date", "见输入清单"),
                    ]
                    for code, qa in official.items()
                ],
            )
            + "<p>超过独立参考截止日期的新增数据仅通过结构、币种、公司行为与内部一致性校验，尚未获得第二来源核验。研究计算仍截断至持仓快照日期，较新的源数据不会造成未来信息泄漏。</p>"
            + "</section>"
        )
    parts.append(
        "<section><h2>费用敏感性与实施检查</h2>"
        + table(
            ["组合"] + [str(b) + " bps" for b in r["configuration"]["cost_bps_scenarios"]] + ["交易费用实值"],
            [
                [label] + [number(s["cost_cny"]) for s in c["cost"]["sensitivity"]] + ["未知"]
                for label, c in candidates.items()
            ],
        )
        + """<p>费率乘买入与卖出总成交金额；单边换手为权重绝对变化总和的一半。管理费及托管费已反映在历史基金净值内，不重复扣除。
        整手、最小订单、赎回阶梯费用、申购额度、溢折价和现金到账时差未核实时，候选权重不生成订单。</p></section>"""
    )
    parts.append(
        "<section><h2>含后续再平衡费用的历史情景</h2><p>每个可观测端点恢复目标权重，扣初始调整及后续按成交额计费。以下仍是回套历史，不是未来回报预测；最低佣金、赎回阶梯、溢折价和冲击另有缺口。</p>"
        + table(
            ["组合"] + [str(b) + " bps 净累计收益" for b in r["configuration"]["cost_bps_scenarios"]],
            [
                [label] + [pct(s["net_compound_return"]) for s in c["net_cost_path_scenarios"]]
                for label, c in candidates.items()
            ],
        )
        + "</section>"
    )
    attribution = current["historical_attribution"]
    parts.append(
        "<section><h2>当前仓位的历史损益与尾部贡献</h2><p>收益是年化算术均值贡献；回撤按初始权重买入持有的同一峰谷计算，各项可加总。周 CVaR 贡献使用组合最差尾部样本，样本很少。这些不是实际账户损益。</p>"
        + table(
            ["产品", "历史算术收益贡献", "周 CVaR95 贡献", "买入持有回撤贡献"],
            [
                [
                    p["code"],
                    pct(attribution["annualized_arithmetic_return_components"][i]),
                    pct(attribution["weekly_cvar95_components"][i]),
                    pct(attribution["buy_hold_max_drawdown_components"][i]),
                ]
                for i, p in enumerate(r["positions"])
            ],
        )
        + "</section>"
    )
    parts.append("""<section><h2>下一次什么变化会改变结论</h2><ol><li>持仓市值变化：重新读取 SSOT，核对日期后重算权重和贡献。</li>
    <li>基金新披露：保留旧版本，更新完整持仓 / Top10 标记及覆盖率，复核重叠变化。</li>
    <li>历史净值修订或新增：检查来源哈希、异常值、日期和币种，重新估计协方差与候选。</li>
    <li>补入约束或成本：重新求解并验证可行性；不可行时停止候选输出。</li></ol></section>""")
    parts.append(
        "<details><summary>全部证据缺口与方法限制</summary><ul>"
        + "".join("<li>" + escape(f) + "</li>" for f in r["flags"])
        + "</ul></details>"
    )
    parts.append(
        "<section><h2>原始披露链接</h2><ul>"
        + "".join(
            '<li><a href="'
            + escape(x["url"], quote=True)
            + '">'
            + escape(x["fund"] + " 半年报原文")
            + "</a> · "
            + escape(x["pages"])
            + " 页 · 持仓 "
            + x["holding_date"]
            + " / 发布 "
            + x["published_date"]
            + "</li>"
            for x in r["disclosure_qa"].get("full_equity", [])
        )
        + "</ul></section>"
    )
    provenance = r.get("data_provenance", {})
    parts.append(
        "<section><h2>复现与来源</h2>"
        + table(
            ["输入", "来源说明"],
            [[key, value] for key, value in provenance.items()],
        )
        + """
    <p>本目录的 <a href="decision.json">decision.json</a> 保存全部指标与假设，<a href="manifest.json">manifest.json</a> 保存输入及输出 SHA-256、代码版本和依赖版本。
    <a href="candidate_weights.csv">候选权重</a>、<a href="weekly_returns.csv">共同周收益</a>、<a href="covariance.csv">协方差</a>、<a href="exposure_matrix.csv">穿透矩阵</a> 可独立核算。</p></section>"""
    )
    css = """body{font:16px/1.7 "Segoe UI","Microsoft YaHei",sans-serif;background:#f4f5f2;color:#172831;margin:0}main{max-width:1220px;margin:auto;padding:48px 28px}header{background:#183c42;color:white;padding:38px;border-radius:14px}h1{font-size:38px;line-height:1.2;margin:16px 0}h2{font-size:24px;margin:0 0 14px}h3{font-size:18px}p{max-width:1060px}.eyebrow{letter-spacing:2px;font-size:12px}.badge{display:inline-block;border:1px solid #91b5b1;padding:5px 12px;border-radius:20px;font-size:13px}section,details{background:white;padding:30px;margin:22px 0;border:1px solid #dfe5df;border-radius:12px}.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}.kpis article{display:flex;flex-direction:column}.kpis b{font-size:32px;color:#205652}.kpis small,.small{font-size:13px;color:#5b6a70}.scroll{overflow:auto;margin:18px 0}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:12px 10px;text-align:right;border-bottom:1px solid #e4e9e6;white-space:nowrap}th{background:#eaf0eb;color:#274c49}td:first-child,th:first-child{text-align:left}tr:hover td{background:#f3f7f3}.notice{border-left:4px solid #bc8d42;padding:12px 18px;background:#fbf6eb}a{color:#246d74}summary{cursor:pointer;font-weight:600}footer{font-size:12px;color:#61716d;margin:30px 0}@media(max-width:760px){main{padding:18px 12px}header,section{padding:20px}.kpis{grid-template-columns:1fr}h1{font-size:28px}}@media print{body{background:white}main{padding:0}section{break-inside:avoid}.scroll{overflow:visible}table{font-size:10px}}"""
    path.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Portfolio Decision Report</title><style>'
        + css
        + "</style><main>"
        + "".join(parts)
        + "<footer>事实 / 历史估计 / 模型结果 / 投资判断保持分离。此报告不连接交易账户。</footer></main></html>",
        "utf-8",
    )
