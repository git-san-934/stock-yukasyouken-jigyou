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


FOREIGN = re.compile(r"常任代理人|[A-Za-zＡ-Ｚａ-ｚ]{4,}")
FINANCIAL = re.compile(r"銀行|信託|証券|生命|保険|共済|カストディ|農林中央金庫|信用金庫")


def holder_kind(name: str) -> str:
    """大株主を所有者別状況の区分に寄せて分類する: foreign / financial / person / other"""
    if FOREIGN.search(name):
        return "foreign"
    if FINANCIAL.search(name):
        return "financial"
    if is_person(name):
        return "person"
    return "other"


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


# ---- 有報の文章から読む手がかり ----
ZEN = str.maketrans("０１２３４５６７８９．％", "0123456789.%")
DATE = re.compile(r"(昭和|平成|令和)?\s*(\d{1,4}|元)\s*年\s*(\d{1,2})\s*月")
ERA = {"昭和": 1925, "平成": 1988, "令和": 2018}
TODAY = (2026, 10)
OTHER_CO = re.compile(r"(?<!当社)(株式会社|㈱|\(株\)|（株）|Corporation|Inc\.|子会社)(?!.*当社)")
CEO = re.compile(r"(?<!副)社長|ＣＥＯ|CEO|最高経営責任者")
CEO_ENTRY = re.compile(r"(取締役|執行役|執行役員)\s*社長|^\s*(当社|同社)?\s*社長|(?<!共同)(?<!共同 )CEO|最高経営責任者")
REP = re.compile(r"代表執行役|代表取締役")
SHACHO = re.compile(r"(?<!副)社長")
REP_ENTRY = re.compile(r"代表執行役|代表取締役(?!副)(?!専務)(?!常務)")


def _norm(t: str) -> str:
    return (t or "").translate(ZEN)


def _entries(career: str):
    """略歴を (年, 月, その行の文) に分ける"""
    t = _norm(career)
    ms = list(DATE.finditer(t))
    out = []
    for i, m in enumerate(ms):
        era, y, mo = m.group(1), m.group(2), int(m.group(3))
        y = 1 if y == "元" else int(y)
        if era:
            y += ERA[era]
        elif y < 100:
            continue
        if not (1950 <= y <= TODAY[0] + 1 and 1 <= mo <= 12):
            continue
        out.append((y, mo, t[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(t)]))
    return out


def ceo_since(d, filer=""):
    """社長（なければ代表取締役）の就任年月。役員の状況の役職名と略歴から読む"""
    core = re.sub(r"株式会社|\s|　", "", filer)[:6]
    cur = re.compile(r"[(（]現(任|在)?[)）]")

    def ours(t):
        return "当社" in t or t.lstrip().startswith("同") or (core and core in re.sub(r"\s|　", "", t)) or not OTHER_CO.search(t)

    for suffix in ("Proposal", ""):  # 総会後の新体制（議案）があればそちらを優先
        titles = d.get(f"jpcrp_cor:OfficialTitleOrPositionInformationAboutDirectorsAndCorporateAuditors{suffix}", {})
        careers = d.get(f"jpcrp_cor:CareerSummaryInformationAboutDirectorsAndCorporateAuditors{suffix}TextBlock", {})
        for title_re, entry_re in ((SHACHO, CEO_ENTRY), (CEO, CEO_ENTRY), (CEO, REP_ENTRY), (REP, REP_ENTRY)):
            for ctx, title in titles.items():
                if not title_re.search(_norm(title)) or ctx not in careers:
                    continue
                ents = _entries(careers[ctx])
                ok = [entry_re.search(e[2]) is not None and ours(e[2]) for e in ents]
                idx = [i for i, e in enumerate(ents) if ok[i] and cur.search(e[2])] or [i for i in range(len(ents)) if ok[i]]
                if idx:
                    i = idx[-1]
                    while i > 0 and ok[i - 1]:  # 「社長 CEO」→「社長」のような肩書の言い換えは就任とみなさない
                        i -= 1
                    return ents[i][:2]
    return None


def text_flags(d, meta):
    pol = _norm(text_of(d, "jpcrp_cor:BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock"))
    if pol:
        meta["capcost"] = 1 if re.search(r"資本コスト|PBR|株価純資産倍率|株価を意識", pol) else 0
        m = re.search(r"(?:ROE|ＲＯＥ|自己資本利益率|株主資本利益率)[^。／]{0,30}?(\d{1,2}(?:\.\d)?)\s*%", pol)
        if m:
            meta["roe_target"] = float(m.group(1)) / 100
    div = _norm(text_of(d, "jpcrp_cor:DividendPolicyTextBlock"))
    if div:
        tags = []
        if re.search(r"累進", div):
            tags.append("累進配当")
        if re.search(r"DOE|ＤＯＥ|株主資本配当率|純資産配当率|自己資本配当率", div):
            tags.append("DOE")
        m = re.search(r"(総還元性向|配当性向)[^。]{0,20}?(\d{1,3}(?:\.\d)?)\s*%(?=[^。]{0,8}(以上|目安|目標|程度|基準|基本|を目処|をめど|水準))", div)
        if m:
            tags.append(f"{m.group(1)}{m.group(2)}%")
        meta["div_policy"] = "・".join(tags)
    sh = text_of(d, "jpcrp_cor:ShareholdingsTextBlock")
    if sh:
        meta["xhold_cut"] = 1 if re.search(r"縮減|削減|売却を進め|売却する方針|全て売却|売却を検討|順次売却", sh) else 0
    amt = 0
    for nm in ("CarryingAmountSharesOtherThanThoseNotListedInvestmentSharesHeldForPurposesOtherThanPureInvestmentReportingCompany",
               "CarryingAmountSharesNotListedInvestmentSharesHeldForPurposesOtherThanPureInvestmentReportingCompany"):
        v = num(d.get("jpcrp_cor:" + nm, {}).get("CurrentYearInstant", ""))
        if v:
            amt += v
    if amt and meta.get("mcap") and amt / meta["mcap"] <= 3:
        meta["xhold_to_mcap"] = amt / meta["mcap"]
    par = _norm(text_of(d, "jpcrp_cor:InformationAboutParentCompanyEtcOfReportingCompanyTextBlock"))
    if par:
        meta["parent"] = 0 if re.search(r"親会社等?は(あり|有り)ません|該当事項は(あり|有り)ません|該当事項なし|親会社等はない", par) else 1
    since = ceo_since(d, meta.get("name", ""))
    if since:
        y, mo = since
        meta["ceo_since"] = f"{y}-{mo:02d}"
        meta["new_ceo"] = 1 if (TODAY[0] - y) * 12 + TODAY[1] - mo <= 24 else 0


# ---- 設備投資・キャッシュフロー ----
NO_PLAN = re.compile(r"(特記すべき事項|特記事項|該当事項|計画)は(あり|有り)ません|(特記事項|該当事項)なし|計画はない")


def _strip_head(t: str) -> str:
    return re.sub(r"^\s*[0-9０-９]+\s*【[^】]*】\s*", "", t or "").strip()


def capex_info(d, meta, pick, first_of):
    sales = meta.get("sales")
    capex = first_of(["jpcrp_cor:CapitalExpendituresOverviewOfCapitalExpendituresEtc", "jpigp_cor:CapitalExpendituresIFRS"])
    cf = [num(d.get(e, {}).get("CurrentYearDuration", "")) for e in (
        "jppfs_cor:PurchaseOfPropertyPlantAndEquipmentInvCF", "jppfs_cor:PurchaseOfIntangibleAssetsInvCF",
        "jppfs_cor:PurchaseOfNoncurrentAssetsInvCF", "jpigp_cor:PurchaseOfPropertyPlantAndEquipmentInvCFIFRS",
        "jpigp_cor:PurchaseOfIntangibleAssetsInvCFIFRS")]
    cf_capex = sum(abs(v) for v in cf if v) or None
    if capex is None or capex <= 0:
        capex = cf_capex
    if capex is not None and sales and capex > sales * 5:  # 単位違いなどの異常値
        capex = None
    meta["capex"] = capex
    dep = first_of(["jppfs_cor:DepreciationAndAmortizationOpeCF", "jppfs_cor:DepreciationOpeCF",
                    "jpigp_cor:DepreciationAndAmortizationOpeCFIFRS", "jpigp_cor:DepreciationAndAmortisationExpenseOpeCFIFRS"])
    meta["depreciation"] = dep if dep and dep > 0 else None
    if capex and sales and sales > 0:
        meta["capex_to_sales"] = capex / sales
    if capex and meta["depreciation"]:
        meta["capex_to_dep"] = capex / meta["depreciation"]
    S = lambda x: f"jpcrp_cor:{x}SummaryOfBusinessResults"
    ope = first_of([S("NetCashProvidedByUsedInOperatingActivities"), S("CashFlowsFromUsedInOperatingActivitiesIFRS"),
                    S("CashFlowsFromUsedInOperatingActivitiesUSGAAP"), "jppfs_cor:NetCashProvidedByUsedInOperatingActivities",
                    "jpigp_cor:NetCashProvidedByUsedInOperatingActivitiesIFRS"])
    inv = first_of([S("NetCashProvidedByUsedInInvestingActivities"), S("CashFlowsFromUsedInInvestingActivitiesIFRS"),
                    S("CashFlowsFromUsedInInvestingActivitiesUSGAAP"), "jppfs_cor:NetCashProvidedByUsedInInvestmentActivities",
                    "jpigp_cor:NetCashProvidedByUsedInInvestingActivitiesIFRS"])
    meta["ope_cf"], meta["inv_cf"] = ope, inv
    if ope is not None and inv is not None:
        meta["fcf"] = ope + inv
    ma = [num(d.get(e, {}).get("CurrentYearDuration", "")) for e in (
        "jppfs_cor:PurchaseOfInvestmentsInSubsidiariesResultingInChangeInScopeOfConsolidationInvCF",
        "jpigp_cor:PaymentsForAcquisitionOfSubsidiariesInvCFIFRS",
        "jppfs_cor:PaymentsForAcquisitionOfBusinessesInvCF", "jpigp_cor:PaymentsForAcquisitionOfBusinessesInvCFIFRS")]
    meta["ma_amount"] = sum(abs(v) for v in ma if v) or None
    sec = [num(d.get(e, {}).get("CurrentYearDuration", "")) for e in (
        "jppfs_cor:PurchaseOfInvestmentSecuritiesInvCF", "jpigp_cor:PurchaseOfInvestmentSecuritiesInvCFIFRS",
        "jpigp_cor:PurchaseOfOtherFinancialAssetsInvCFIFRS")]
    meta["sec_purchase"] = sum(abs(v) for v in sec if v) or None

    ov = _strip_head(text_of(d, "jpcrp_cor:OverviewOfCapitalExpendituresEtcTextBlock"))
    if ov:
        meta["capex_text"] = ov[:1000]
    pl = _strip_head(text_of(d, "jpcrp_cor:PlannedAdditionsRetirementsEtcOfFacilitiesTextBlock"))
    if pl:
        new = re.split(r"[(（]\s*[2２]\s*[)）]\s*重要な設備の除却|重要な設備の除却", pl)[0]
        new = re.sub(r"^[(（]\s*[1１]\s*[)）]\s*重要な設備の新設等?\s*", "", new).strip()
        meta["plan_text"] = new[:2000]
        meta["plan"] = 0 if (NO_PLAN.search(new) and len(new) < 120) or not new else 1
        m = re.search(r"(設備投資|投資)[^。]{0,8}(計画|予定)[^。]{0,60}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(億円|百万円|千円)", _norm(new))
        if m:
            unit = {"億円": 1e8, "百万円": 1e6, "千円": 1e3}[m.group(4)]
            amt = float(m.group(3).replace(",", "")) * unit
            if not sales or amt <= sales * 5:
                meta["plan_amount"] = amt


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

        # 全株式の内訳: 浮動株 + 大株主 + 投資信託等(金融機関) + 外国人 + その他 = 100%
        # 区分ごとの割合から、その区分に入る大株主の分を差し引いて二重計上を避ける
        cat = lambda *els: sum((units(e) or 0) for e in els) / u_tot if u_tot else None
        fin = cat("jpcrp_cor:NumberOfSharesHeldNumberOfUnitsFinancialInstitutions",
                  "jpcrp_cor:NumberOfSharesHeldNumberOfUnitsFinancialServiceProviders")
        frn = cat("jpcrp_cor:NumberOfSharesHeldNumberOfUnitsForeignInvestorsOtherThanIndividuals",
                  "jpcrp_cor:NumberOfSharesHeldNumberOfUnitsForeignIndividualInvestors")
        if fin is not None and holders:
            by = defaultdict(float)
            for name, _, ratio in holders:
                by[holder_kind(name)] += (ratio or 0) * outstanding_share
            big = sum(by.values())
            meta["bd_big"] = big
            meta["bd_fund"] = max(0.0, fin - by["financial"])
            meta["bd_foreign"] = max(0.0, frn - by["foreign"])
            meta["bd_other"] = max(0.0, 1 - meta["float_ratio"] - big - meta["bd_fund"] - meta["bd_foreign"])

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

    # 営業利益率（連結を優先、なければ単体）。銀行など営業利益のない業種は空欄
    for nc in (False, True):
        sfx = "_NonConsolidatedMember" if nc else ""
        op, *_ = first(d, [("jppfs_cor:OperatingIncome", "CurrentYearDuration" + sfx),
                           ("jpigp_cor:OperatingProfitLossIFRS", "CurrentYearDuration" + sfx)])
        sales, *_ = first(d, [("jppfs_cor:NetSales", "CurrentYearDuration" + sfx),
                              ("jpigp_cor:RevenueIFRS", "CurrentYearDuration" + sfx),
                              ("jpigp_cor:NetSalesIFRS", "CurrentYearDuration" + sfx)])
        sales = sales or summary_sales(d, nc)
        # 銀行・保険は OperatingIncome が「経常収益」を指すので、9割超は使わない
        limit = 0.9 if "gross_margin" in meta else 0.5  # 売上総利益のない金融業は特に紛れやすい
        if op is not None and sales and -5 <= op / sales <= limit:
            meta["op_margin"] = op / sales
            break
        if not nc and summary_sales(d, False):
            break  # 連結決算の会社で単体の数字は使わない（持株会社の単体は意味が違う）

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
    if price and not 1 <= price[0] <= 300000:  # 株価データの異常値（yfinance）は使わない
        price = None
    factor = 1  # 決算期後の株式分割の倍率（推定）
    split_unknown = False
    if price and fy_price:
        r = fy_price / price[0]
        if r > 1.8:
            f = min((2, 3, 4, 5, 10, 20, 50, 100), key=lambda f: abs(r / f - 1))
            if 0.6 < r / f < 1.6:
                factor = f
                meta["split_adj"] = f
            else:
                split_unknown = True
    if price:
        meta["price"], meta["price_date"] = price
        if dps is not None and not split_unknown:
            meta["div_yield"] = dps / factor / price[0]
            # 期中の株式分割や特別配当でゆがみやすいので、高すぎる利回りは要確認にする
            if meta["div_yield"] > 0.08 or "split_adj" in meta:
                meta["yield_check"] = 1

    # ---- 投資指標 ----
    def pick(names, kinds=("Duration",)):
        cands = []
        for nm in names:
            for k in kinds:
                cands += [(nm, f"CurrentYear{k}"), (nm, f"CurrentYear{k}_NonConsolidatedMember")]
        return first(d, cands)[0]

    S = lambda x: f"jpcrp_cor:{x}SummaryOfBusinessResults"
    eps = pick([S("BasicEarningsLossPerShare"), S("BasicEarningsLossPerShareIFRS"), S("BasicEarningsLossPerShareUSGAAP")])
    bps = pick([S("NetAssetsPerShare"), S("EquityToAssetRatioIFRS"),  # IFRS は名前と違い1株当たり親会社所有者帰属持分
                S("EquityAttributableToOwnersOfParentPerShareUSGAAP")], ("Instant",))
    meta["roe"] = pick([S("RateOfReturnOnEquity"), S("RateOfReturnOnEquityIFRS"), S("RateOfReturnOnEquityUSGAAP")])
    meta["equity_ratio"] = pick([S("EquityToAssetRatio"), S("RatioOfOwnersEquityToGrossAssetsIFRS"),
                                 S("EquityToAssetRatioUSGAAP")], ("Instant",))
    if meta["roe"] is not None and abs(meta["roe"]) >= 2:
        meta["roe"] = meta["roe"] / 100  # ％表記で入っている会社
    if meta["equity_ratio"] is not None and meta["equity_ratio"] > 1.5:
        meta["equity_ratio"] = meta["equity_ratio"] / 100  # ％表記で入っている会社
    if meta["equity_ratio"] is not None and not -1 <= meta["equity_ratio"] <= 1:
        meta["equity_ratio"] = None
    if price and not split_unknown:
        p0 = price[0] * factor  # 決算期の株数ベースに戻した株価
        if eps and eps > 0 and p0 / eps <= 1000:
            meta["per"] = p0 / eps
        if bps and bps > 0 and p0 / bps <= 100:
            meta["pbr"] = p0 / bps
        if issued and p0 * (issued - treasury) >= 1e8:
            meta["mcap"] = p0 * (issued - treasury)
    mcap = meta.get("mcap")
    if mcap and cash is not None:
        meta["cash_to_mcap"] = cash / mcap

    # 有利子負債（連結優先）
    DEBT = ["jppfs_cor:ShortTermLoansPayable", "jppfs_cor:LongTermLoansPayable",
            "jppfs_cor:CurrentPortionOfLongTermLoansPayable", "jppfs_cor:BondsPayable",
            "jppfs_cor:CurrentPortionOfBonds", "jppfs_cor:CommercialPapersLiabilities",
            "jppfs_cor:ShortTermBondsPayable", "jppfs_cor:ConvertibleBondTypeBondsWithSubscriptionRightsToShares",
            "jppfs_cor:BondsWithSubscriptionRightsToSharesNCL",
            "jpigp_cor:BondsAndBorrowingsCLIFRS", "jpigp_cor:BondsAndBorrowingsNCLIFRS",
            "jpigp_cor:BorrowingsCLIFRS", "jpigp_cor:BorrowingsNCLIFRS",
            "jpigp_cor:InterestBearingLiabilitiesCLIFRS", "jpigp_cor:InterestBearingLiabilitiesNCLIFRS",
            "jpigp_cor:BondsPayableCLIFRS", "jpigp_cor:BondsPayableNCLIFRS",
            "jpigp_cor:CurrentPortionOfLongTermBorrowingsCLIFRS", "jpigp_cor:BondsAndBorrowingsLiabilitiesIFRS",
            "jpigp_cor:BorrowingsLiabilitiesIFRS"]
    for ctx in ("CurrentYearInstant", "CurrentYearInstant_NonConsolidatedMember"):
        vals = [num(d.get(e, {}).get(ctx, "")) for e in DEBT]
        if any(v is not None for v in vals) or ctx.endswith("Member"):
            meta["debt"] = sum(v for v in vals if v)
            break
    if mcap and cash is not None:
        meta["netcash_to_mcap"] = (cash - meta["debt"]) / mcap

    # 前期比（売上・営業利益、連結優先）
    def pair(names):
        for sfx in ("", "_NonConsolidatedMember"):
            for nm in names:
                cur = num(d.get(nm, {}).get("CurrentYearDuration" + sfx, ""))
                pri = num(d.get(nm, {}).get("Prior1YearDuration" + sfx, ""))
                if cur is not None and pri:
                    return cur, pri
        return None, None
    cur, pri = pair(["jppfs_cor:NetSales", "jpigp_cor:RevenueIFRS", "jpigp_cor:NetSalesIFRS",
                     S("NetSales"), S("RevenueIFRS"), S("OperatingRevenue1"), S("RevenuesUSGAAP")])
    if cur is not None and pri > 0:
        meta["sales_growth"] = cur / pri - 1
    cur, pri = pair(["jppfs_cor:OperatingIncome", "jpigp_cor:OperatingProfitLossIFRS"])
    if cur is not None and pri:
        meta["op_growth"] = (cur - pri) / abs(pri)

    # 従業員
    meta["employees"] = pick(["jpcrp_cor:NumberOfEmployees"], ("Instant",))
    def years(kind):
        """「○年○ヶ月」形式で年と月が別の要素になっている会社は月を足す"""
        el = f"jpcrp_cor:Average{kind}{{}}InformationAboutReportingCompanyInformationAboutEmployees"
        y = pick([el.format("Years")], ("Instant",))
        mo = pick([el.format("Months")], ("Instant",))
        if y is not None and mo is not None and float(y).is_integer() and 0 <= mo < 12:
            y += mo / 12
        return y

    meta["avg_age"] = years("Age")
    meta["avg_tenure"] = years("LengthOfService")
    if meta["avg_tenure"] is not None and not 0 <= meta["avg_tenure"] <= 50:
        meta["avg_tenure"] = None
    sal = pick(["jpcrp_cor:AverageAnnualSalaryInformationAboutReportingCompanyInformationAboutEmployees"], ("Instant",))
    if sal is not None and sal < 100000:
        sal *= 1000  # 千円単位で入っている会社
    elif sal is not None and sal > 1e8:
        sal /= 1000
    meta["avg_salary"] = sal if sal is not None and 1e6 <= sal <= 5e7 else None
    age = meta["avg_age"]
    if age is not None and not 18 <= age <= 70:
        meta["avg_age"] = None

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
    text_flags(d, meta)

    def first_of(names):
        for nm in names:
            for ctx in ("CurrentYearDuration", "CurrentYearDuration_NonConsolidatedMember"):
                v = num(d.get(nm, {}).get(ctx, ""))
                if v is not None:
                    return v
        return None
    capex_info(d, meta, pick, first_of)
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
