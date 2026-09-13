#!/usr/bin/env python3
"""
Fetches daily closes for the portfolio ETFs into data/prices.json.

Usage:  python3 scripts/fetch_prices.py [--from 2026-01-01]

Source is justETF's public chart endpoint. Everything is requested in EUR at
market value with dividends excluded, so the five funds are directly
comparable and the numbers match what a EUR-based broker account shows —
the USD-denominated funds therefore include the FX move, which is real.

Rerunning overwrites data/prices.json. Run scripts/build_site.py afterwards;
the price data is inlined into index.html at build time.
"""

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prices.json"

# ISIN is the identity that matters — share class (Acc vs Dist) and listing
# currency both change the series, so these are pinned deliberately.
FUNDS = [
    ("IAEX", "IE00B0M62Y33", "AEX index",
     "iShares AEX UCITS ETF"),
    ("EUEA", "IE0008471009", "EURO STOXX 50",
     "iShares Core EURO STOXX 50 UCITS ETF EUR (Dist)"),
    ("IWDA", "IE00B4L5Y983", "MSCI World",
     "iShares Core MSCI World UCITS ETF USD (Acc)"),
    ("VUSA", "IE00B3XXRP09", "S&P 500",
     "Vanguard S&P 500 UCITS ETF (USD) Distributing"),
    ("VHYL", "IE00B8GKDB10", "FTSE All-World High Dividend",
     "Vanguard FTSE All-World High Dividend Yield UCITS ETF Distributing"),
]

ENDPOINT = (
    "https://www.justetf.com/api/etfs/{isin}/performance-chart"
    "?locale=en&currency=EUR&valuesType=MARKET_VALUE"
    "&reduceData=false&includeDividends=false&features=DIVIDENDS"
    "&dateFrom={date_from}&dateTo={date_to}"
)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch(isin, date_from, date_to):
    url = ENDPOINT.format(isin=isin, date_from=date_from, date_to=date_to)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", default=None,
                    help="start date (default: 1 Jan of the current year)")
    ap.add_argument("--to", dest="date_to",
                    default=dt.date.today().isoformat())
    args = ap.parse_args()
    date_from = args.date_from or f"{dt.date.today().year}-01-01"

    series, meta, latest = {}, [], ""
    for ticker, isin, short, name in FUNDS:
        try:
            doc = fetch(isin, date_from, args.date_to)
        except (urllib.error.URLError, TimeoutError) as e:
            sys.exit(f"{ticker} ({isin}): fetch failed — {e}\n"
                     f"data/prices.json left unchanged.")

        points = doc.get("series") or []
        if not points:
            sys.exit(f"{ticker} ({isin}): no data returned. "
                     f"data/prices.json left unchanged.")

        # The feed carries every calendar day, repeating the last close over
        # weekends. Keep weekdays only so the series is one row per session.
        closes = {}
        for p in points:
            d = p["date"]
            if dt.date.fromisoformat(d).weekday() < 5:
                closes[d] = round(float(p["value"]["raw"]), 2)

        series[ticker] = closes
        last = max(closes)
        latest = max(latest, last)
        meta.append({"ticker": ticker, "isin": isin, "short": short,
                     "name": name, "currency": "EUR"})
        print(f"  {ticker:5} {isin}  {len(closes):3} closes  "
              f"{min(closes)} → {last}  ({closes[last]})")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "justETF performance-chart API",
        "basis": "Market value in EUR, dividends excluded (price return).",
        "fetched": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated": latest,
        "tickers": meta,
        "series": series,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT.relative_to(ROOT)} — latest close {latest}")


if __name__ == "__main__":
    main()
