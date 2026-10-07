"""有価証券報告書 (XBRL CSV) から銘柄スクリーニング用の数値を集める。

data/<コード>/meta.json の docID ごとに CSV(type=5) を取り、株主構成・財務・配当・
自己株式に関係しそうな要素を当期分だけ抜き出して screen/raw.jsonl.gz に書く。
集計（不動株割合などの計算）はこの生データを別途処理して行う。

  python scripts/extract_metrics.py --dump 6113 8306   # 全要素を screen/dump/ に出す（タグ確認用）
  python scripts/extract_metrics.py --all --workers 4   # 全銘柄
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from edinet_common import DATA, ROOT
from extract_business import _ensure_csv_zip, _iter_csv_rows
from htmltext import html_to_text

OUT = ROOT / "screen"

KEEP = re.compile(
    r"MajorShareholder|ShareholdingRatio|NumberOfSharesHeld|TreasuryShare|TreasuryStock"
    r"|Officer|IssuedShares|SummaryOfBusinessResults|GrossProfit|NetSales|Revenue"
    r"|CashAndDeposits|CashAndCashEquivalents|OperatingIncome|OperatingProfit|Dividend|ShareholderCategory|Shareholders"
    r"|PercentageOfShareholdings|SharesWithFullVotingRights|VotingRights|SecurityCodeDEI|FilerName|FiscalYear"
    r"|AccountingStandardsDEI|WhetherConsolidated"
    r"|LoansPayable|Bonds|Borrowings|CommercialPaper|InterestBearing"
    r"|Employees|AverageAge|AverageAnnualSalary|AverageLengthOfService"
    r"|InvestmentSharesHeldForPurposesOtherThanPureInvestment",
    re.I,
)
SKIP_CONTEXT = re.compile(r"^Prior", re.I)
# 前期比を出すため、売上・営業利益だけは前期の値も残す
PRIOR_OK = re.compile(r"NetSales|Revenue|OperatingIncome|OperatingProfit")


# マルチプル改善の手がかりになる文章。全文は大きいので、キーワードの前後だけ残す
SNIPPET_BLOCKS = {
    "jpcrp_cor:BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock":
        r"資本コスト|PBR|ＰＢＲ|株価純資産倍率|株価を意識|ROE|ＲＯＥ|自己資本利益率|株主資本利益率|総還元性向|政策保有",
    "jpcrp_cor:ShareholdingsTextBlock": r"縮減|削減|売却を進め|売却する方針|保有しない|ゼロ|全て売却",
}
FULL_BLOCKS = {  # 短いので先頭から残す
    "jpcrp_cor:DividendPolicyTextBlock": 3000,
    "jpcrp_cor:InformationAboutParentCompanyEtcOfReportingCompanyTextBlock": 400,
}
CAREER = re.compile(r"CareerSummaryInformationAboutDirectorsAndCorporateAuditors(Proposal)?TextBlock$")


def _snippets(text: str, pattern: str, width: int = 70, limit: int = 8) -> str:
    out = []
    for m in re.finditer(pattern, text):
        out.append(text[max(0, m.start() - width): m.end() + width])
        if len(out) >= limit:
            break
    return " ／ ".join(out)


def _rows(doc_id: str):
    zip_path = _ensure_csv_zip(doc_id)
    try:
        for _name, row in _iter_csv_rows(zip_path):
            yield row
    finally:
        pass


def collect(code: str, doc_id: str) -> dict:
    out = []
    for row in _rows(doc_id):
        el = (row.get("要素ID") or "").strip()
        ctx = (row.get("コンテキストID") or "").strip()
        val = (row.get("値") or "").strip()
        if not val:
            continue
        if SKIP_CONTEXT.match(ctx) and not (ctx.startswith("Prior1YearDuration") and PRIOR_OK.search(el)):
            continue
        if el.endswith("TextBlock"):
            if "TreasuryShare" in el or el.startswith("jpcrp_cor:AcquisitionsBy"):
                out.append([el, ctx, val[:3000]])
            elif el in SNIPPET_BLOCKS:
                snip = _snippets(html_to_text(val), SNIPPET_BLOCKS[el])
                out.append([el, ctx, snip or "（該当語なし）"])
            elif el in FULL_BLOCKS:
                out.append([el, ctx, html_to_text(val)[:FULL_BLOCKS[el]]])
            elif CAREER.search(el):
                out.append([el, ctx, html_to_text(val)[:2500]])
            continue
        if "OfficialTitleOrPositionInformationAboutDirectorsAndCorporateAuditors" in el:
            out.append([el, ctx, val[:100]])
            continue
        if KEEP.search(el):
            out.append([el, ctx, val[:200]])
    shutil.rmtree((ROOT / "cache" / "docs" / doc_id), ignore_errors=True)
    return {"code": code, "doc_id": doc_id, "rows": out}


def dump(code: str) -> None:
    meta = json.loads((DATA / code / "meta.json").read_text(encoding="utf-8"))
    dest = OUT / "dump" / f"{code}.tsv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        for row in _rows(meta["doc_id"]):
            fh.write("\t".join([
                row.get("要素ID") or "", row.get("項目名") or "",
                row.get("コンテキストID") or "", row.get("ユニットID") or "",
                (row.get("値") or "").replace("\t", " ").replace("\n", " ")[:120],
            ]) + "\n")
    print("dumped", dest)


def run_all(workers: int, limit: int | None) -> None:
    metas = []
    for p in sorted(DATA.glob("*/meta.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        metas.append((p.parent.name, m["doc_id"]))
    if limit:
        metas = metas[:limit]
    dest = OUT / "raw.jsonl.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    failures = []
    done = 0
    with gzip.open(dest, "wt", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(collect, c, d): c for c, d in metas}
        for fut in as_completed(futs):
            code = futs[fut]
            try:
                fh.write(json.dumps(fut.result(), ensure_ascii=False) + "\n")
            except BaseException as err:  # SystemExit も拾う
                failures.append([code, str(err)[:200]])
            done += 1
            if done % 200 == 0:
                print(f"{done}/{len(metas)} failures={len(failures)}", flush=True)
    (OUT / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=1))
    print(f"done {done} failures={len(failures)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    for c in a.dump or []:
        dump(c)
    if a.all:
        run_all(a.workers, a.limit)
    sys.exit(0)
