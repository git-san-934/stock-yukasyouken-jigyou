import json, sys, math
import pandas as pd
metrics, jpx_path, out, updated = sys.argv[1:5]
m = pd.read_csv(metrics, dtype={"code": str})
markets = {}
try:
    j = pd.read_csv(jpx_path, dtype=str)
    markets = dict(zip(j["コード"].str.strip(), j["市場・商品区分"]))
    sectors = dict(zip(j["コード"].str.strip(), j["33業種区分"]))
    # 銀行・保険の「営業利益」は経常収益などを指すため、営業利益率は出さない
    fin = m["code"].map(sectors).isin(["銀行業", "保険業"])
    m.loc[fin, "op_margin"] = None
    # 銀行・保険・証券は預金や顧客資産で現金・負債がふくらむので、現金や負債を時価総額と比べる指標は出さない
    fin2 = m["code"].map(sectors).isin(["銀行業", "保険業", "証券、商品先物取引業"])
    m.loc[fin2, ["cash_to_mcap", "netcash_to_mcap"]] = None
except Exception as e:
    print("no jpx", e)
m["market"] = m["code"].map(markets)
if markets:
    m = m[m["market"].fillna("").str.contains("プライム|スタンダード|グロース")]
def v(x, r=None):
    if x is None or (isinstance(x, float) and math.isnan(x)) or x == "": return None
    return round(float(x), r) if r is not None else x
rows = []
for _, r in m.iterrows():
    rows.append({
        "c": r.code, "n": r["name"], "m": v(r.get("market")),
        "f": v(r.get("float_ratio"), 5),
        "bb": v(r.get("bd_big"), 4), "bf": v(r.get("bd_fund"), 4),
        "bx": v(r.get("bd_foreign"), 4), "bo": v(r.get("bd_other"), 4), "b": v(r.get("fixed_B"), 4), "a": v(r.get("fixed_A"), 4),
        "g": v(r.get("gross_margin"), 4), "om": v(r.get("op_margin"), 4),
        "cash": v(r.get("cash") / 1e6 if pd.notna(r.get("cash")) else None, 0),
        "y": v(r.get("div_yield"), 4), "yc": 1 if r.get("yield_check") == 1 else 0, "d": v(r.get("dps"), 2),
        "bs": 1 if str(r.get("buyback_status", "")).startswith(("取締役会", "株主総会")) else 0,
        "ba": v(r.get("buyback_amount") / 1e6 if pd.notna(r.get("buyback_amount")) else None, 0),
        "t": v(r.get("treasury_ratio"), 4), "top1": v(r.get("top1")),
        "fy": v(r.get("period_end")),
        "mc": v(r.get("mcap") / 1e6 if pd.notna(r.get("mcap")) else None, 0),
        "pe": v(r.get("per"), 2), "pb": v(r.get("pbr"), 3), "roe": v(r.get("roe"), 4),
        "er": v(r.get("equity_ratio"), 4), "cm": v(r.get("cash_to_mcap"), 4), "nc": v(r.get("netcash_to_mcap"), 4),
        "sg": v(r.get("sales_growth"), 4), "og": v(r.get("op_growth"), 4),
        "em": v(r.get("employees"), 0), "ag": v(r.get("avg_age"), 1),
        "sl": v(r.get("avg_salary") / 1e4 if pd.notna(r.get("avg_salary")) else None, 0),
        "cc": v(r.get("capcost"), 0), "rt": v(r.get("roe_target"), 4), "dp": v(r.get("div_policy")),
        "xc": v(r.get("xhold_cut"), 0), "xm": v(r.get("xhold_to_mcap"), 4), "pa": v(r.get("parent"), 0),
        "cs": v(r.get("ceo_since")), "nw": v(r.get("new_ceo"), 0),
    })
fy = m["period_end"].dropna()
pd_ = m["price_date"].dropna() if "price_date" in m else pd.Series([], dtype=str)
doc = {"updated": updated, "fy_range": f"{fy.min()[:7]}〜{fy.max()[:7]}期" if len(fy) else "",
       "price_date": pd_.max() if len(pd_) else "", "rows": rows}
json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(len(rows), "rows ->", out)
