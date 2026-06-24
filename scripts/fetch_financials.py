#!/usr/bin/env python3
"""
fetch_financials.py - SOFA Financial Data Fetcher
Uses yfinance to pull structured financial data for SOFA financial bridge work.

Usage:
  python fetch_financials.py TICKER                    # full snapshot (all modules)
  python fetch_financials.py TICKER quote              # quote + fast_info only
  python fetch_financials.py TICKER income             # income statement
  python fetch_financials.py TICKER balance             # balance sheet
  python fetch_financials.py TICKER cashflow            # cash flow statement
  python fetch_financials.py TICKER valuation           # valuation multiples + comps hint
  python fetch_financials.py TICKER holders             # institutional holders
  python fetch_financials.py TICKER recommendations     # analyst recommendations
  python fetch_financials.py TICKER earnings            # earnings history + dates
  python fetch_financials.py TICKER dividends           # dividend history
  python fetch_financials.py TICKER profile             # company profile

Ticker format:
  US stocks:    AAPL, MSFT, NVDA
  HK stocks:    0700.HK (Tencent), 9988.HK (Alibaba)
  A-shares:     600519.SS (Kweichow Moutai, Shanghai), 000858.SZ (Wuliangye, Shenzhen)
  Indices:      ^GSPC (S&P500), ^IXIC (Nasdaq)
  ETFs:         SMH, SOXX, ARKK
"""

import sys
import json
import traceback
from datetime import datetime

def safe_val(v):
    """Convert numpy/pandas types to JSON-serializable Python types."""
    if v is None:
        return None
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            if np.isnan(v):
                return None
            return float(v)
        if isinstance(v, np.bool_):
            return bool(v)
    except ImportError:
        pass
    try:
        import pandas as pd
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
    except ImportError:
        pass
    if isinstance(v, float):
        import math
        if math.isnan(v):
            return None
    return v

def fmt_number(n, prefix="", suffix=""):
    """Format large numbers for readability."""
    if n is None:
        return "N/A"
    n = safe_val(n)
    if isinstance(n, (int, float)):
        abs_n = abs(n)
        if abs_n >= 1e12:
            return f"{prefix}{n/1e12:.2f}T{suffix}"
        elif abs_n >= 1e9:
            return f"{prefix}{n/1e9:.2f}B{suffix}"
        elif abs_n >= 1e6:
            return f"{prefix}{n/1e6:.2f}M{suffix}"
        elif abs_n >= 1e3:
            return f"{prefix}{n/1e3:.1f}K{suffix}"
        else:
            return f"{prefix}{n:.2f}{suffix}"
    return str(n)

def get_quote(ticker):
    """Get current quote and fast_info."""
    info = ticker.fast_info
    result = {
        "module": "quote",
        "timestamp": datetime.now().isoformat(),
        "last_price": safe_val(info.get("lastPrice")),
        "currency": safe_val(info.get("currency")),
        "market_cap": safe_val(info.get("marketCap")),
        "market_cap_fmt": fmt_number(safe_val(info.get("marketCap"))),
        "shares_outstanding": safe_val(info.get("shares")),
        "day_high": safe_val(info.get("dayHigh")),
        "day_low": safe_val(info.get("dayLow")),
        "previous_close": safe_val(info.get("previousClose")),
        "50d_avg": safe_val(info.get("fiftyDayAverage")),
        "200d_avg": safe_val(info.get("twoHundredDayAverage")),
        "year_high": safe_val(info.get("yearHigh")),
        "year_low": safe_val(info.get("yearLow")),
        "year_change_pct": safe_val(info.get("yearChange")),
        "avg_volume_10d": safe_val(info.get("tenDayAverageVolume")),
        "avg_volume_3m": safe_val(info.get("threeMonthAverageVolume")),
        "exchange": safe_val(info.get("exchange")),
        "quote_type": safe_val(info.get("quoteType")),
    }
    return result

def get_profile(ticker):
    """Get company profile info."""
    info = ticker.info or {}
    fields = [
        "longName", "shortName", "sector", "industry", "subIndustry",
        "country", "city", "website", "longBusinessSummary",
        "fullTimeEmployees", "exchange", "quoteType",
        "totalRevenue", "revenuePerShare", "revenueGrowth",
        "grossMargins", "operatingMargins", "profitMargins",
        "totalCash", "totalDebt", "debtToEquity",
        "returnOnEquity", "returnOnAssets",
        "currentPrice", "targetHighPrice", "targetLowPrice",
        "targetMeanPrice", "targetMedianPrice", "recommendationKey",
        "numberOfAnalystOpinions",
        "forwardPE", "trailingPE", "priceToBook", "priceToSalesTrailing12Months",
        "forwardEps", "trailingEps",
        "bookValue", "enterpriseValue", "enterpriseToRevenue", "enterpriseToEbitda",
        "freeCashflow", "operatingCashflow",
        "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
        "sharesOutstanding", "floatShares",
        "heldPercentInsiders", "heldPercentInstitutions",
        "shortRatio", "shortPercentOfFloat",
    ]
    result = {"module": "profile", "timestamp": datetime.now().isoformat()}
    for f in fields:
        result[f] = safe_val(info.get(f))
    return result

def get_income_statement(ticker):
    """Get income statement (annual + quarterly)."""
    result = {"module": "income_statement", "timestamp": datetime.now().isoformat()}

    # Annual
    try:
        annual = ticker.income_stmt
        if annual is not None and not annual.empty:
            annual_data = {}
            for col in annual.columns:
                year = col.strftime("%Y") if hasattr(col, "strftime") else str(col)
                annual_data[year] = {}
                for idx in annual.index:
                    val = safe_val(annual.loc[idx, col])
                    annual_data[year][str(idx)] = val
            result["annual"] = annual_data
        else:
            result["annual"] = None
    except Exception as e:
        result["annual"] = None
        result["annual_error"] = str(e)

    # Quarterly
    try:
        quarterly = ticker.quarterly_income_stmt
        if quarterly is not None and not quarterly.empty:
            q_data = {}
            for col in quarterly.columns:
                qname = col.strftime("%Y-Q%q") if hasattr(col, "strftime") else str(col)
                qname = col.strftime("%Y-%m") if hasattr(col, "strftime") else str(col)
                q_data[qname] = {}
                for idx in quarterly.index:
                    val = safe_val(quarterly.loc[idx, col])
                    q_data[qname][str(idx)] = val
            result["quarterly"] = q_data
        else:
            result["quarterly"] = None
    except Exception as e:
        result["quarterly"] = None
        result["quarterly_error"] = str(e)

    return result

def get_balance_sheet(ticker):
    """Get balance sheet (annual + quarterly)."""
    result = {"module": "balance_sheet", "timestamp": datetime.now().isoformat()}

    try:
        annual = ticker.balance_sheet
        if annual is not None and not annual.empty:
            annual_data = {}
            for col in annual.columns:
                year = col.strftime("%Y") if hasattr(col, "strftime") else str(col)
                annual_data[year] = {}
                for idx in annual.index:
                    annual_data[year][str(idx)] = safe_val(annual.loc[idx, col])
            result["annual"] = annual_data
        else:
            result["annual"] = None
    except Exception as e:
        result["annual"] = None
        result["annual_error"] = str(e)

    try:
        quarterly = ticker.quarterly_balance_sheet
        if quarterly is not None and not quarterly.empty:
            q_data = {}
            for col in quarterly.columns:
                qname = col.strftime("%Y-%m") if hasattr(col, "strftime") else str(col)
                q_data[qname] = {}
                for idx in quarterly.index:
                    q_data[qname][str(idx)] = safe_val(quarterly.loc[idx, col])
            result["quarterly"] = q_data
        else:
            result["quarterly"] = None
    except Exception as e:
        result["quarterly"] = None
        result["quarterly_error"] = str(e)

    return result

def get_cashflow(ticker):
    """Get cash flow statement (annual + quarterly)."""
    result = {"module": "cashflow", "timestamp": datetime.now().isoformat()}

    try:
        annual = ticker.cashflow
        if annual is not None and not annual.empty:
            annual_data = {}
            for col in annual.columns:
                year = col.strftime("%Y") if hasattr(col, "strftime") else str(col)
                annual_data[year] = {}
                for idx in annual.index:
                    annual_data[year][str(idx)] = safe_val(annual.loc[idx, col])
            result["annual"] = annual_data
        else:
            result["annual"] = None
    except Exception as e:
        result["annual"] = None
        result["annual_error"] = str(e)

    try:
        quarterly = ticker.quarterly_cashflow
        if quarterly is not None and not quarterly.empty:
            q_data = {}
            for col in quarterly.columns:
                qname = col.strftime("%Y-%m") if hasattr(col, "strftime") else str(col)
                q_data[qname] = {}
                for idx in quarterly.index:
                    q_data[qname][str(idx)] = safe_val(quarterly.loc[idx, col])
            result["quarterly"] = q_data
        else:
            result["quarterly"] = None
    except Exception as e:
        result["quarterly"] = None
        result["quarterly_error"] = str(e)

    return result

def get_valuation(ticker):
    """Get valuation metrics and ratios."""
    info = ticker.info or {}
    result = {
        "module": "valuation",
        "timestamp": datetime.now().isoformat(),
        "market_cap": safe_val(info.get("marketCap")),
        "market_cap_fmt": fmt_number(safe_val(info.get("marketCap"))),
        "enterprise_value": safe_val(info.get("enterpriseValue")),
        "enterprise_value_fmt": fmt_number(safe_val(info.get("enterpriseValue"))),
        # Multiples
        "trailing_pe": safe_val(info.get("trailingPE")),
        "forward_pe": safe_val(info.get("forwardPE")),
        "peg_ratio": safe_val(info.get("pegRatio")),
        "price_to_book": safe_val(info.get("priceToBook")),
        "price_to_sales_ttm": safe_val(info.get("priceToSalesTrailing12Months")),
        "ev_to_revenue": safe_val(info.get("enterpriseToRevenue")),
        "ev_to_ebitda": safe_val(info.get("enterpriseToEbitda")),
        # Per-share
        "trailing_eps": safe_val(info.get("trailingEps")),
        "forward_eps": safe_val(info.get("forwardEps")),
        "book_value": safe_val(info.get("bookValue")),
        # Margins
        "gross_margin": safe_val(info.get("grossMargins")),
        "operating_margin": safe_val(info.get("operatingMargins")),
        "profit_margin": safe_val(info.get("profitMargins")),
        # Returns
        "roe": safe_val(info.get("returnOnEquity")),
        "roa": safe_val(info.get("returnOnAssets")),
        # Cash flow
        "free_cashflow": safe_val(info.get("freeCashflow")),
        "operating_cashflow": safe_val(info.get("operatingCashflow")),
        "fcf_fmt": fmt_number(safe_val(info.get("freeCashflow"))),
        # Dividends
        "dividend_yield": safe_val(info.get("dividendYield")),
        "payout_ratio": safe_val(info.get("payoutRatio")),
        # Analyst targets
        "target_high": safe_val(info.get("targetHighPrice")),
        "target_low": safe_val(info.get("targetLowPrice")),
        "target_mean": safe_val(info.get("targetMeanPrice")),
        "target_median": safe_val(info.get("targetMedianPrice")),
        "recommendation": safe_val(info.get("recommendationKey")),
        "num_analysts": safe_val(info.get("numberOfAnalystOpinions")),
        # Shares
        "shares_outstanding": safe_val(info.get("sharesOutstanding")),
        "float_shares": safe_val(info.get("floatShares")),
        "short_ratio": safe_val(info.get("shortRatio")),
        "short_pct_float": safe_val(info.get("shortPercentOfFloat")),
        # Beta
        "beta": safe_val(info.get("beta")),
    }

    # Compute DuPont if possible
    try:
        net_margin = safe_val(info.get("profitMargins"))
        asset_turnover = safe_val(info.get("assetTurnover"))  # Not always available
        roe_val = safe_val(info.get("returnOnEquity"))
        equity_multiplier = safe_val(info.get("equityMultiplier"))  # Not always available

        # Try to compute from balance sheet + income stmt
        if net_margin and roe_val:
            result["dupont_net_margin"] = net_margin
            result["dupont_roe"] = roe_val
            if equity_multiplier:
                result["dupont_equity_multiplier"] = equity_multiplier
                result["dupont_asset_turnover_calc"] = safe_val(
                    roe_val / (net_margin * equity_multiplier) if net_margin * equity_multiplier != 0 else None
                )
    except Exception:
        pass

    return result

def get_holders(ticker):
    """Get institutional and insider holders."""
    result = {"module": "holders", "timestamp": datetime.now().isoformat()}

    try:
        inst = ticker.institutional_holders
        if inst is not None and not inst.empty:
            holders_list = []
            for _, row in inst.head(15).iterrows():
                holders_list.append({
                    "holder": str(row.get("Holder", "")),
                    "shares": safe_val(row.get("Shares")),
                    "date_reported": str(row.get("Date Reported", "")),
                    "pct_outstanding": safe_val(row.get("% Out")),
                })
            result["institutional_top15"] = holders_list
        else:
            result["institutional_top15"] = None
    except Exception as e:
        result["institutional_top15"] = None
        result["institutional_error"] = str(e)

    try:
        insiders = ticker.major_holders
        if insiders is not None and not insiders.empty:
            result["major_holders_summary"] = {}
            for _, row in insiders.iterrows():
                result["major_holders_summary"][str(row.iloc[1])] = safe_val(row.iloc[0])
        else:
            result["major_holders_summary"] = None
    except Exception as e:
        result["major_holders_summary"] = None

    return result

def get_recommendations(ticker):
    """Get analyst recommendations and upgrades/downgrades."""
    result = {"module": "recommendations", "timestamp": datetime.now().isoformat()}

    try:
        recs = ticker.recommendations
        if recs is not None and not recs.empty:
            rec_list = []
            recent = recs.tail(20)  # last 20
            for idx, row in recent.iterrows():
                rec_list.append({
                    "date": str(idx),
                    "firm": str(row.get("Firm", "")),
                    "to_grade": str(row.get("To Grade", "")),
                    "from_grade": str(row.get("From Grade", "")),
                    "action": str(row.get("Action", "")),
                })
            result["recent_upgrades_downgrades"] = rec_list
        else:
            result["recent_upgrades_downgrades"] = None
    except Exception as e:
        result["recent_upgrades_downgrades"] = None
        result["error"] = str(e)

    return result

def get_earnings(ticker):
    """Get earnings history and upcoming dates."""
    result = {"module": "earnings", "timestamp": datetime.now().isoformat()}

    # Earnings dates
    try:
        cal = ticker.calendar
        if cal is not None:
            if isinstance(cal, dict):
                result["calendar"] = {k: safe_val(v) for k, v in cal.items()}
            else:
                result["calendar"] = str(cal)
        else:
            result["calendar"] = None
    except Exception as e:
        result["calendar"] = None
        result["calendar_error"] = str(e)

    # Earnings history
    try:
        eh = ticker.earnings_history
        if eh is not None and not eh.empty:
            history = []
            for _, row in eh.tail(12).iterrows():
                history.append({
                    "quarter": str(row.get("quarter", "")),
                    "eps_estimate": safe_val(row.get("epsEstimate")),
                    "eps_actual": safe_val(row.get("epsActual")),
                    "surprise_pct": safe_val(row.get("epsDifference")),
                })
            result["earnings_history_last12"] = history
        else:
            result["earnings_history_last12"] = None
    except Exception as e:
        result["earnings_history_last12"] = None
        result["earnings_error"] = str(e)

    return result

def get_dividends(ticker):
    """Get dividend history."""
    result = {"module": "dividends", "timestamp": datetime.now().isoformat()}

    try:
        divs = ticker.dividends
        if divs is not None and not divs.empty:
            div_list = []
            for date, amount in divs.tail(20).items():
                div_list.append({
                    "date": str(date),
                    "amount": safe_val(amount),
                })
            result["recent_dividends"] = div_list
        else:
            result["recent_dividends"] = None
            result["note"] = "No dividend history found"
    except Exception as e:
        result["recent_dividends"] = None
        result["error"] = str(e)

    return result


def full_snapshot(ticker_symbol):
    """Get everything in one call."""
    import yfinance as yf
    ticker = yf.Ticker(ticker_symbol)
    results = []
    for fn in [get_quote, get_profile, get_income_statement, get_balance_sheet,
               get_cashflow, get_valuation, get_holders, get_recommendations,
               get_earnings, get_dividends]:
        try:
            results.append(fn(ticker))
        except Exception as e:
            results.append({"module": fn.__name__, "error": str(e)})
    return results


MODULE_MAP = {
    "quote": get_quote,
    "profile": get_profile,
    "income": get_income_statement,
    "balance": get_balance_sheet,
    "cashflow": get_cashflow,
    "valuation": get_valuation,
    "holders": get_holders,
    "recommendations": get_recommendations,
    "earnings": get_earnings,
    "dividends": get_dividends,
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_financials.py TICKER [module]")
        print("Modules: quote, profile, income, balance, cashflow, valuation, holders, recommendations, earnings, dividends")
        print("Default: full snapshot (all modules)")
        sys.exit(1)

    ticker_symbol = sys.argv[1].upper()
    module = sys.argv[2].lower() if len(sys.argv) > 2 else "all"

    import yfinance as yf

    try:
        if module == "all":
            result = full_snapshot(ticker_symbol)
        elif module in MODULE_MAP:
            ticker = yf.Ticker(ticker_symbol)
            result = MODULE_MAP[module](ticker)
        else:
            print(json.dumps({"error": f"Unknown module: {module}", "available": list(MODULE_MAP.keys())}))
            sys.exit(1)

        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    except Exception as e:
        print(json.dumps({"error": str(e), "ticker": ticker_symbol, "traceback": traceback.format_exc()}))
        sys.exit(1)


if __name__ == "__main__":
    main()
