# Data sources and reuse boundaries

Reviewed on 2026-10-21. This register describes the sources referenced by the adapters. It does not grant permission to collect or redistribute their data. The MIT license covers this project's code, not third-party disclosures, identifiers, prices, or logos.

The public demo, screenshots, and release examples contain synthetic data only. CI does not call the source adapters. No scheduled collection is enabled by this repository.

## Source register

| Adapter | Source and endpoint scope | Reviewed notice | Permission status and limits |
| --- | --- | --- | --- |
| `official_ishares.py` | iShares US product pages and holdings downloads on `ishares.com` | [BlackRock corporate terms](https://www.blackrock.com/corporate/compliance/terms-and-conditions); [iShares FTP terms](https://www.ishares.com/us/literature/holdings/fdf-terms-of-use.pdf) | The corporate terms restrict automated retrieval without permission and public or commercial reuse. The FTP terms apply to a separate delivery service and contain additional data and third-party identifier restrictions. Neither document establishes a license for this adapter's product-page downloads. Applicable product-page permission remains unconfirmed. |
| `official_efunds.py` | 易方达基金, `efunds.com.cn` and `api.efunds.com.cn`, public announcement indexes and linked reports | [Official homepage](https://www.efunds.com.cn/); [online trading agreement](https://www.efunds.com.cn/html/upd/efiles/protocols/OpenSecuritiesInvestmentFundOnlineTradeProtocol.html) | The trading agreement concerns an account service. It is not evidence of permission to scrape or redistribute public reports. A public-data reuse license and automated-access terms were not verified. |
| `official_fsfund.py` | 华宝基金 / Hwabao Fund, `fsfund.com` and `api.fsfund.com`, fund disclosures and linked reports | [Official English disclaimer](https://www.fsfund.com/eng/eng_mzsm.shtml); [current Chinese disclaimer page](https://www.fsfund.com/helpCenter/disclaimers.shtml) | The English notice restricts commercial use of protected material without permission. The Chinese page's substantive text was not available in the reviewed extraction. Automated-access permission and redistribution rights remain unconfirmed. `fsfund.com` is 华宝基金, not 富国基金. |
| `official_sse.py` | 上海证券交易所, ETF announcement pages and `query.sse.com.cn` | [SSE legal notice](https://www.sse.com.cn/home/legal/); [SSE information authorization statement](https://www.sseinfo.com/aboutus/authstatement/) | The website notice permits non-commercial browsing and downloading under its conditions and restricts use for resale without written permission. The separate information authorization statement adds licensing requirements for exchange information. These notices do not establish an unrestricted data redistribution license or automated-query quota. |

## Collection frequency

No numeric request allowance was verified for these endpoints. This project does not treat an undocumented endpoint, a successful HTTP response, or `robots.txt` as an access license.

The repository defines no approved polling interval for any source. Live collection requires source-specific permission and a documented collection policy. The public demonstration uses generated local inputs and makes no requests to these providers.

## Project publication policy

- Do not commit downloaded disclosures, holdings files, provider responses, account records, cookies, or credentials to the public repository.
- Do not distribute third-party datasets or identifiable account-derived reports in release assets without documented reuse rights.
- Do not bypass authentication, CAPTCHAs, access denials, rate limits, or other access controls.
- Do not present this project's calculations as provider-endorsed results.
- Keep any permitted local evidence with its source URL, retrieval date, disclosure date, publication date, and the applicable permission record.

Before enabling a source for a live workflow, record the applicable terms URL, review date, authorized delivery method, request policy, and permitted recipients. If permission remains uncertain, keep that source out of the live workflow and use synthetic inputs for public examples.

See [input contracts](DATA.md) for the data schema. Schema validation and hash verification establish neither data accuracy nor reuse permission.
