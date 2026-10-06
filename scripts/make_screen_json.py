import json, sys, math
import pandas as pd
metrics, jpx_path, out, updated = sys.argv[1:5]
m = pd.read_csv(metrics, dtype={"code": str})
markets = {}
try:
    j = pd.read_csv(jpx_path, dtype=str)
    markets = dict(zip(j["コード"].str.strip(), j["市場・商品区分"]))
except Exception as e:
    print("no jpx", e)
m["market"] = m["code"].map(markets)
if markets:
    m = m[m["market"].fillna("").str.contains("プライム|スタンダード|グロース")]
def v(x, r=None):
    if x is None or (isinstance(x, float) and math.isnan(x)): return None
    return round(float(x), r) if r is not None else x
rows = []
for _, r in m.iterrows():
    rows.append({
        "c": r.code, "n": r["name"], "m": v(r.get("market")),
        "f": v(r.get("float_ratio"), 5), "b": v(r.get("fixed_B"), 4), "a": v(r.get("fixed_A"), 4),
        "g": v(r.get("gross_margin"), 4),
        "cash": v(r.get("cash") / 1e6 if pd.notna(r.get("cash")) else None, 0),
        "y": v(r.get("div_yield"), 4), "yc": 1 if r.get("yield_check") == 1 else 0, "d": v(r.get("dps"), 2),
        "bs": 1 if str(r.get("buyback_status", "")).startswith(("取締役会", "株主総会")) else 0,
        "ba": v(r.get("buyback_amount") / 1e6 if pd.notna(r.get("buyback_amount")) else None, 0),
        "t": v(r.get("treasury_ratio"), 4), "top1": v(r.get("top1")),
        "fy": v(r.get("period_end")),
    })
fy = m["period_end"].dropna()
pd_ = m["price_date"].dropna() if "price_date" in m else pd.Series([], dtype=str)
doc = {"updated": updated, "fy_range": f"{fy.min()[:7]}〜{fy.max()[:7]}期" if len(fy) else "",
       "price_date": pd_.max() if len(pd_) else "", "rows": rows}
json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(len(rows), "rows ->", out)
