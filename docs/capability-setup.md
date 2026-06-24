# Capability Setup

SOFA detects optional tools and prints recommendations. It never silently installs tools, writes credentials, or changes host configuration without explicit user approval.

Run the capability check when you want to see what is available:

```bash
python SOFA/scripts/capability_check.py
python SOFA/scripts/capability_check.py --json
```

## General Search Chain

SOFA recommends this search/fetch order:

1. AnySearch: https://github.com/anysearch-ai/anysearch-skill
2. Exa MCP server: https://github.com/exa-labs/exa-mcp-server
3. Tavily skills or CLI: https://github.com/tavily-ai/skills
4. Host built-ins

Missing search tools do not stop research, but they lower confidence in search completeness and should be recorded in `capability_report.md`.

## Wind For Chinese Financial Data

For Chinese users or China-market financial work, read this page before installation:

https://aifinmarket.wind.com.cn/skill.md

GitHub install commands:

```bash
npx skills add Wind-Information-Co-Ltd/wind-skills --skill wind-find-finance-skill -g -y
npx skills add Wind-Information-Co-Ltd/wind-skills --skill wind-mcp-skill -g -y
```

Gitee alternatives:

```bash
npx skills add https://gitee.com/wind_info/wind-skills.git --skill wind-mcp-skill -g -y
npx skills add https://gitee.com/wind_info/wind-skills.git --skill wind-find-finance-skill -g -y
```

SOFA must ask before writing `WIND_API_KEY` or any other credential.

## yfinance For Global Public Markets

For English/global public-market snapshots:

```bash
python -m pip install yfinance
```

`yfinance` is useful for quote, profile, financial statement, valuation, holder, recommendation, earnings, and dividend snapshots. Filings, exchange announcements, and company disclosures remain authoritative.

## Confidence Rule

If a financial data capability is missing, the financial bridge should say so and lower confidence. Do not replace missing structured financial data with unsupported assumptions.
