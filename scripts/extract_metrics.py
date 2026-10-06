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

OUT = ROOT / "screen"

KEEP = re.compile(
    r"MajorShareholder|ShareholdingRatio|NumberOfSharesHeld|TreasuryShare|TreasuryStock"
    r"|Officer|IssuedShares|SummaryOfBusinessResults|GrossProfit|NetSales|Revenue"
    r"|CashAndDeposits|CashAndCashEquivalents|Dividend|ShareholderCategory|Shareholders"
    r"|SharesWithFullVotingRights|VotingRights|SecurityCodeDEI|FilerName|FiscalYear"
    r"|AccountingStandardsDEI|WhetherConsolidated",
    re.I,
)
SKIP_CONTEXT = re.compile(r"^Prior", re.I)


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
        if not val or SKIP_CONTEXT.match(ctx):
            continue
        if el.endswith("TextBlock"):
            if "TreasuryShare" in el or "TreasuryStock" in el:
                out.append([el, ctx, val[:6000]])
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
