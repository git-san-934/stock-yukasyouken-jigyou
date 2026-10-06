"""JPX の東証上場銘柄一覧 (data_j.xls) を取って screen/jpx_list.csv に書く。"""
from __future__ import annotations

import io

import pandas as pd
import requests

from edinet_common import ROOT

BASE = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/"

for name in ("data_j.xlsx", "data_j.xls"):
    resp = requests.get(BASE + name, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    if resp.ok:
        break
resp.raise_for_status()
df = pd.read_excel(io.BytesIO(resp.content), dtype=str)
out = ROOT / "screen" / "jpx_list.csv"
df.to_csv(out, index=False, encoding="utf-8")
print(len(df), "rows ->", out)
