"""data/ の全銘柄の直近終値を Yahoo Finance (yfinance) から取って screen/prices.csv に書く。"""
from __future__ import annotations

import csv
import sys
import time

import yfinance as yf

from edinet_common import DATA, ROOT


def main(limit: int | None = None) -> None:
    codes = sorted(p.name for p in DATA.iterdir() if (p / "meta.json").exists())
    if limit:
        codes = codes[:limit]
    got: dict[str, tuple[str, float]] = {}
    for attempt in range(4):
        todo = [c for c in codes if c not in got]
        if not todo:
            break
        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            tickers = [f"{c}.T" for c in chunk]
            try:
                df = yf.download(tickers, period="10d", interval="1d", auto_adjust=False,
                                 group_by="ticker", progress=False, threads=False)
            except Exception as err:
                print("download error", err)
                time.sleep(10)
                continue
            for c, t in zip(chunk, tickers):
                try:
                    s = df[t]["Close"].dropna()
                    got[c] = (str(s.index[-1].date()), float(s.iloc[-1]))
                except Exception:
                    pass
            time.sleep(2)
        print(f"attempt {attempt}: {len(got)}/{len(codes)}", flush=True)
        time.sleep(30)
    rows = [[c, *got[c]] if c in got else [c, "", ""] for c in codes]
    out = ROOT / "screen" / "prices.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "date", "close"])
        w.writerows(rows)
    print("prices:", sum(1 for r in rows if r[2] != ""), "/", len(rows))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
