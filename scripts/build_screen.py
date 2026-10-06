"""screen/raw.jsonl.gz（extract_metrics.py の出力）と screen/prices.csv から
銘柄ごとの指標を計算して screen/metrics.csv に書く。

  python scripts/build_screen.py [raw.jsonl.gz] [prices.csv] [out.csv]

不動株割合は2通り計算する（いずれも発行済株式総数に対する割合）。
  A 特定株比率（四季報式）   = 上位10大株主 + 役員持株 + 自己株式等
  B 固定株比率（東証式の近似）= 10%以上の大株主（信託口・カストディ名義を除く）
                               + 役員持株 + 自己株式等
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# 信託銀行の信託口や海外カストディアンの名義株は実質的な保有者ではないので B では固定株に数えない
CUSTODY = re.compile(
    r"信託口|投信口|マスタートラスト信託銀行|カストディ|資産管理サービス信託|CUSTOD|STATE\s*STREET|BANK\s*OF\s*NEW\s*YORK|BNYM|"
    r"J\.?\s*P\.?\s*MORGAN|NORTHERN\s*TRUST|SSBTC|NOMURA\s*PB|GOLDMAN|MORGAN\s*STANLEY", re.I)


# 大株主のうち「個人その他」に入る日本の個人を見分ける: 漢字・ひらがなだけの名前で、
# 法人・官庁を示す語を含まないもの（カタカナ・英字の名前は外国法人等の可能性が高いので除く）
NOT_PERSON = re.compile(r"会社|銀行|信託|証券|保険|生命|共済|財団|社団|組合|基金|機構|協会|法人|大臣|政府|"
                        r"持株会|従業員|興産|商事|産業|企画|事務所|[市県都府国省庁]$")
PERSON = re.compile(r"^[\u4e00-\u9fff\u3040-\u309f々〆ヶ\s　]+$")


def is_person(name: str) -> bool:
    if re.search(r"[(（]株[)）]|[(（]有[)）]|㈱|㈲|公司", name):
        return False
    name = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
    return bool(PERSON.match(name)) and not NOT_PERSON.search(name)


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def index(rows):
    d = defaultdict(dict)
    for el, ctx, val in rows:
        d[el].setdefault(ctx, val)
    return d


def first(d, candidates):
    for el, ctx in candidates:
        v = num(d.get(el, {}).get(ctx, ""))
        if v is not None:
            return v, el, ctx
    return None, None, None


def summary_sales(d, nonconsol: bool):
    ctx = "CurrentYearDuration_NonConsolidatedMember" if nonconsol else "CurrentYearDuration"
    for el, ctxs in d.items():
        if el.endswith("SummaryOfBusinessResults") and re.search(r"NetSales|Revenue", el) \
                and not re.search(r"Ratio|PerShare|Cost", el):
            v = num(ctxs.get(ctx, ""))
            if v is not None:
                return v
    return None


def text_of(d, el):
    return next(iter(d.get(el, {}).values()), "")


def compute(rec, prices):
    d = index(rec["rows"])
    meta = {"code": rec["code"], "doc_id": rec["doc_id"]}
    meta["name"] = text_of(d, "jpdei_cor:FilerNameInJapaneseDEI")
    meta["period_end"] = text_of(d, "jpdei_cor:CurrentFiscalYearEndDateDEI")

    issued, *_ = first(d, [
        ("jpcrp_cor:NumberOfIssuedSharesAsOfFiscalYearEndIssuedSharesTotalNumberOfSharesEtc", "FilingDateInstant"),
        ("jpcrp_cor:NumberOfSharesIssuedSharesVotingRights", "CurrentYearInstant"),
        ("jpcrp_cor:TotalNumberOfIssuedSharesSummaryOfBusinessResults", "CurrentYearInstant_NonConsolidatedMember"),
        ("jpcrp_cor:TotalNumberOfIssuedSharesSummaryOfBusinessResults", "CurrentYearInstant"),
    ])
    treasury, *_ = first(d, [
        ("jpcrp_cor:TotalNumberOfSharesHeldTreasurySharesEtc", "CurrentYearInstant"),
        ("jpcrp_cor:TotalNumberOfSharesHeldTreasurySharesEtc", "CurrentYearInstant_Row1Member"),
    ])
    treasury = treasury or 0.0

    holders = []
    for i in range(1, 11):
        ctx = f"CurrentYearInstant_No{i}MajorShareholdersMember"
        sh = num(d.get("jpcrp_cor:NumberOfSharesHeld", {}).get(ctx, ""))
        ratio = num(d.get("jpcrp_cor:ShareholdingRatio", {}).get(ctx, ""))
        name = d.get("jpcrp_cor:NameMajorShareholders", {}).get(ctx, "")
        if sh is not None or ratio is not None:
            # 株数の単位（千株など）を取り違えた報告があるので、割合があれば割合から株数を出す
            if ratio is not None and issued:
                sh = ratio * (issued - treasury)
            if sh is not None:
                holders.append((name, sh, ratio))
    top10 = sum(h[1] for h in holders)
    big10 = sum(h[1] for h in holders
                if (h[2] or 0) >= 0.10 and not CUSTODY.search(re.sub(r"[（(]常任代理人.*", "", h[0])))

    off_el = "jpcrp_cor:NumberOfSharesHeldOrdinarySharesInformationAboutDirectorsAndCorporateAuditors"
    each = [num(v) or 0 for c, v in d.get(off_el, {}).items()
            if c.startswith("FilingDateInstant_")]
    officers = sum(each)
    if not each:
        officers = num(d.get(off_el, {}).get("FilingDateInstant", "")) or 0
        each = [officers]
    # 大株主欄と役員欄の二重計上を避ける: 10位の株数以上を持つ役員は上位10名に、
    # 10%以上を持つ役員は B の大株主に既に含まれているとみなす
    if issued and officers > issued:  # 単位の取り違え（千株・百株）
        for unit in (1000, 100):
            if officers / unit <= issued:
                each = [x / unit for x in each]
                officers /= unit
                break
        else:
            each, officers = [], 0
    tenth = min((h[1] for h in holders), default=0)
    outstanding = (issued or 0) - treasury
    off_A = sum(x for x in each if x < tenth) if tenth else officers
    cap = lambda x: min(x, 1.0)
    off_B = sum(x for x in each if not outstanding or x / outstanding < 0.10)

    if issued and holders:
        meta["fixed_A"] = cap((top10 + off_A + treasury) / issued)
        meta["fixed_B"] = cap((big10 + off_B + treasury) / issued)
    meta["top10_ratio"] = top10 / issued if issued and holders else None
    meta["treasury_ratio"] = treasury / issued if issued else None
    meta["officer_ratio"] = officers / issued if issued else None
    meta["top1"] = f"{holders[0][0]} {holders[0][2]:.1%}" if holders and holders[0][2] else ""

    pct = lambda el: num(d.get(el, {}).get("CurrentYearInstant_OrdinaryShareMember", ""))
    meta["individual_ratio"] = pct("jpcrp_cor:PercentageOfShareholdingsIndividualsAndOthers")

    # ユーザー定義の浮動株 = 全株式 − 大株主 − 金融機関(投信等) − 外国人 − その他法人など
    #   ≒ 所有者別状況の「個人その他」から、自己株式・大株主の個人・役員持株を除いたもの
    units = lambda el: next((num(d.get(el, {}).get(c, "")) for c in
                             ("CurrentYearInstant_OrdinaryShareMember", "CurrentYearInstant")
                             if num(d.get(el, {}).get(c, "")) is not None), None)
    u_ind = units("jpcrp_cor:NumberOfSharesHeldNumberOfUnitsIndividualsAndOthers")
    u_tot = units("jpcrp_cor:NumberOfSharesHeldNumberOfUnitsTotal")
    ind = u_ind / u_tot if u_ind is not None and u_tot else meta["individual_ratio"]
    if ind is not None and issued:
        outstanding_share = (issued - treasury) / issued
        big_ind = sum(h[2] for h in holders if h[2] and is_person(h[0])) * outstanding_share
        own, *_ = first(d, [("jpcrp_cor:NumberOfSharesHeldInOwnNameTreasurySharesEtc", "CurrentYearInstant"),
                            ("jpcrp_cor:NumberOfSharesHeldInOwnNameTreasurySharesEtc", "CurrentYearInstant_Row1Member")])
        own = treasury if own is None else own
        if own / issued > ind:  # 自己株式を「個人その他」に含めていない会社
            own = 0
        meta["float_ratio"] = max(0.0, ind - own / issued - big_ind - off_A / issued)
        meta["big_individual_ratio"] = big_ind

    # 粗利率（連結を優先、なければ単体）
    for nc in (False, True):
        sfx = "_NonConsolidatedMember" if nc else ""
        gp, *_ = first(d, [("jppfs_cor:GrossProfit", "CurrentYearDuration" + sfx),
                           ("jpigp_cor:GrossProfitIFRS", "CurrentYearDuration" + sfx)])
        sales, *_ = first(d, [("jppfs_cor:NetSales", "CurrentYearDuration" + sfx),
                              ("jpigp_cor:RevenueIFRS", "CurrentYearDuration" + sfx),
                              ("jpigp_cor:NetSalesIFRS", "CurrentYearDuration" + sfx)])
        sales = sales or summary_sales(d, nc)
        if gp is not None and sales and gp / sales <= 1:
            meta["gross_margin"] = gp / sales
            meta["gm_basis"] = "単体" if nc else "連結"
            break
    meta["sales"] = summary_sales(d, False) or summary_sales(d, True)

    cash, el, ctx = first(d, [
        ("jppfs_cor:CashAndDeposits", "CurrentYearInstant"),
        ("jpigp_cor:CashAndCashEquivalentsIFRS", "CurrentYearInstant"),
        ("jpcrp_cor:CashAndCashEquivalentsIFRSSummaryOfBusinessResults", "CurrentYearInstant"),
        ("jpcrp_cor:CashAndCashEquivalentsSummaryOfBusinessResults", "CurrentYearInstant"),
        ("jppfs_cor:CashAndDeposits", "CurrentYearInstant_NonConsolidatedMember"),
    ])
    meta["cash"] = cash
    if el:
        meta["cash_basis"] = ("現金及び預金" if "Deposits" in el else "現金及び現金同等物") + \
            ("（単体）" if "NonConsolidated" in ctx else "")

    dps, *_ = first(d, [
        ("jpcrp_cor:DividendPaidPerShareSummaryOfBusinessResults", "CurrentYearDuration_NonConsolidatedMember"),
        ("jpcrp_cor:DividendPaidPerShareSummaryOfBusinessResults", "CurrentYearDuration"),
    ])
    meta["dps"] = dps
    meta["payout"], *_ = first(d, [
        ("jpcrp_cor:PayoutRatioSummaryOfBusinessResults", "CurrentYearDuration_NonConsolidatedMember"),
        ("jpcrp_cor:PayoutRatioSummaryOfBusinessResults", "CurrentYearDuration")])
    # 決算期末の株価の目安 = PER × EPS（株式分割の検出に使う）
    fy_price = None
    for sfx in ("", "IFRS", "USGAAP"):
        for ctx in ("CurrentYearDuration", "CurrentYearDuration_NonConsolidatedMember"):
            per = num(d.get(f"jpcrp_cor:PriceEarningsRatio{sfx}SummaryOfBusinessResults", {}).get(ctx, ""))
            eps = num(d.get(f"jpcrp_cor:BasicEarningsLossPerShare{sfx}SummaryOfBusinessResults", {}).get(ctx, ""))
            if per and eps and per > 0 and eps > 0:
                fy_price = per * eps
                break
        if fy_price:
            break
    price = prices.get(rec["code"])
    if price:
        meta["price"], meta["price_date"] = price
        if dps is not None:
            adj = dps
            if fy_price:
                r = fy_price / price[0]
                if r > 1.8:  # 決算期後の株式分割とみなし、分割比率で配当を割る
                    factor = min((2, 3, 4, 5, 10, 20, 50, 100), key=lambda f: abs(r / f - 1))
                    if 0.6 < r / factor < 1.6:
                        adj = dps / factor
                        meta["split_adj"] = factor
                    else:
                        adj = None
            if adj is not None:
                meta["div_yield"] = adj / price[0]
                # 期中の株式分割や特別配当でゆがみやすいので、高すぎる利回りは要確認にする
                if meta["div_yield"] > 0.08 or "split_adj" in meta:
                    meta["yield_check"] = 1

    buy, *_ = first(d, [
        ("jppfs_cor:PurchaseOfTreasuryStockFinCF", "CurrentYearDuration"),
        ("jpigp_cor:PaymentsForPurchaseOfTreasurySharesFinCFIFRS", "CurrentYearDuration"),
        ("jppfs_cor:PurchaseOfTreasuryStock", "CurrentYearDuration"),
        ("jpigp_cor:PurchaseOfTreasurySharesSSIFRS", "CurrentYearDuration"),
        ("jppfs_cor:PurchaseOfTreasuryStockFinCF", "CurrentYearDuration_NonConsolidatedMember"),
        ("jppfs_cor:PurchaseOfTreasuryStock", "CurrentYearDuration_NonConsolidatedMember"),
    ])
    meta["buyback_amount"] = abs(buy) if buy else 0.0
    board = text_of(d, "jpcrp_cor:AcquisitionsByResolutionOfBoardOfDirectorsMeetingTextBlock")
    agm = text_of(d, "jpcrp_cor:AcquisitionsByResolutionOfShareholdersMeetingTextBlock")
    has_board = bool(board) and "該当事項はありません" not in board[:400]
    has_agm = bool(agm) and "該当事項はありません" not in agm[:400]
    amt = meta["buyback_amount"] / 1e6
    if (has_board or has_agm) and amt >= 1:
        s = "取締役会決議による取得あり" if has_board else "株主総会決議による取得あり"
        meta["buyback_status"] = f"{s}（当期取得額 {amt:,.0f}百万円）"
    elif has_board or has_agm:
        meta["buyback_status"] = "取得の決議あり（当期の取得額は1百万円未満）"
    elif amt >= 1:
        meta["buyback_status"] = f"決議による取得なし（単元未満株買取等 {amt:,.0f}百万円）"
    elif amt > 0:
        meta["buyback_status"] = "決議による取得なし（単元未満株買取のみ）"
    else:
        meta["buyback_status"] = "なし"
    return meta


def main():
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "screen" / "raw.jsonl.gz"
    pr = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "screen" / "prices.csv"
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "screen" / "metrics.csv"
    prices = {}
    if pr.exists():
        for r in csv.DictReader(open(pr, encoding="utf-8")):
            if r["close"]:
                prices[r["code"]] = (float(r["close"]), r["date"])
    rows = [compute(json.loads(line), prices) for line in gzip.open(raw, "rt", encoding="utf-8")]
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["code"]))
    print(f"{len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
