"""data/ の全銘柄の直近終値を Yahoo Finance (yfinance) から取って screen/prices.csv に書く。"""
from __future__ import annotations

import csv
import sys

import yfinance as yf

from edinet_common import DATA, ROOT


def main(limit: int | None = None) -> None:
    codes = sorted(p.name for p in DATA.iterdir() if (p / "meta.json").exists())
    if limit:
        codes = codes[:limit]
    rows = []
    for i in range(0, len(codes), 200):
        chunk = codes[i:i + 200]
        tickers = [f"{c}.T" for c in chunk]
        df = yf.download(tickers, period="10d", interval="1d", auto_adjust=False,
                         group_by="ticker", progress=False, threads=True)
        for c, t in zip(chunk, tickers):
            try:
                s = df[t]["Close"].dropna()
                rows.append([c, str(s.index[-1].date()), float(s.iloc[-1])])
            except Exception:
                rows.append([c, "", ""])
    out = ROOT / "screen" / "prices.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "date", "close"])
        w.writerows(rows)
    print("prices:", sum(1 for r in rows if r[2] != ""), "/", len(rows))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
