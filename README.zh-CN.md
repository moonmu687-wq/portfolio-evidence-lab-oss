# Portfolio Evidence Lab

基金穿透与组合风险核验。结果保留来源、日期、计算口径和未知部分。

## 先看效果

[下载 HTML 报告](https://github.com/moonmu687-wq/portfolio-evidence-lab-oss/releases/latest/download/Portfolio_Decision_Report.html)，用浏览器打开即可，无需安装 Python。[完整演示包](https://github.com/moonmu687-wq/portfolio-evidence-lab-oss/releases/latest/download/synthetic-demo.zip) 同时提供报告中引用的 JSON 和 CSV 文件。

![实际生成的合成报告首屏](docs/demo/report-overview.png)

示例已穿透 71.9% 的底层资产，28.1% 保留为未知。虚构基金 990001 占资金的 35%，却贡献约 49% 的估计波动风险。

![合成持仓权重与波动风险贡献](docs/demo/report-weights.png)

图片来自实际运行的 HTML 报告，全部产品、净值、持仓和金额均为虚构。[演示说明](docs/demo/README.md) 列出固定样例结果与复现边界。

## 离线体验

在 Python 3.12 或更高版本的虚拟环境中运行：

```sh
python -m pip install -c requirements.lock .
portfolio-lab demo --destination demo-workspace
```

打开命令打印的 HTML 报告。安装后的演示离线运行，不需要账户、API key 或市场数据订阅。

四只产品、净值、持仓和金额均为明确标注的合成数据。样例的已识别敞口为 71.9%，未知部分为 28.1%，虚构证券 US:SYNTH_A 的组合敞口为 31.15%。这些数值仅用于独立核算测试。

## 功能

递归基金穿透、循环检测、保留未披露部分；证券重叠下限与保守上界；波动、回撤、风险贡献和周频历史 CVaR；有约束研究候选及费用情景；输入、源码与环境留存及离线重放。

[输入契约](docs/DATA.md) 提供字段与完整工作流。[English README](README.md) 提供验证、重放及开发命令。

研究候选不是直接交易指令或未来收益预测。哈希验证不替代对原始数据真实性的判断。

## 数据边界

版本只包含通用代码、文档和合成测试。第三方数据许可与代码 MIT 许可分别处理。

[数据来源登记](docs/DATA_SOURCES.md) 记录已核实条款、未知授权和公开发布边界。公开 CI、演示和发布包不调用真实来源适配器。

## 版本与维护

[Release](https://github.com/moonmu687-wq/portfolio-evidence-lab-oss/releases/latest) 提供 wheel、源码包、合成报告、CSV 与 SHA-256 校验值。[变更记录](CHANGELOG.md) 说明版本内容。

CI 在 Linux、Windows 及 Python 3.12、3.13 上验证，并在源码目录之外安装 wheel、运行演示、核验和重放。`scikit-learn` 用于 Ledoit-Wolf 协方差估计，应保留。

[维护说明](docs/MAINTENANCE.md) 提供截图重建、版本发布和依赖更新流程。尚未配置 PyPI 发布。
