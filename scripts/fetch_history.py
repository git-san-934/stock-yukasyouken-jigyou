"""BPS など1株当たり指標の長期推移を集める。

有報の「主要な経営指標等の推移」には5期分しか載っていないので、
最新の有報に加えて5年前・10年前の有報も取り、つなげて最大15期分にする。

  python fetch_history.py --offsets 0 5 10 [--limit N] [--workers 6]

出力: screen/history.jsonl.gz
  {"code", "offset", "doc_id", "period_end", "rows": [[要素ID, コンテキストID, 値], ...]}
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from edinet_common import DATA, DOC_TYPE_YUHO, ROOT, get_doc_list
from extract_business import _ensure_csv_zip, _iter_csv_rows

OUT = ROOT / "screen"
KEEP = re.compile(r"SummaryOfBusinessResults$|FiscalYearEndDateDEI$|SecurityCodeDEI$")
WANT = re.compile(r"PerShare|EquityToAssetRatio|IssuedShares|NetAssets|Equity")
CTX = re.compile(r"^(CurrentYear|Prior[1-4]Year)(Instant|Duration)(_NonConsolidatedMember)?$|^FilingDateInstant$")


def shift_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 2/29
        return d.replace(year=d.year - years, day=28)


def find_old_docs(metas: list[dict], years: int) -> dict[str, str]:
    """period_end の years 年前の期の有報を、提出日の範囲を日ごとに走査して探す"""
    want = {}
    for m in metas:
        pe = date.fromisoformat(m["period_end"])
        want[m["seccode"]] = shift_years(pe, years).isoformat()[:7]
    pes = [date.fromisoformat(m["period_end"]) for m in metas]
    start = shift_years(min(pes), years)
    end = min(shift_years(max(pes), years) + timedelta(days=130), date.today())
    found: dict[str, tuple[str, str]] = {}
    d = start
    while d <= end:
        try:
            payload = get_doc_list(d.isoformat())
        except Exception as err:  # 1日分の失敗で止めない
            print("doclist failed", d, err, flush=True)
            payload = {}
        for r in payload.get("results") or []:
            sc = r.get("secCode") or ""
            if r.get("docTypeCode") != DOC_TYPE_YUHO or sc not in want:
                continue
            if (r.get("periodEnd") or "")[:7] != want[sc]:
                continue
            if r.get("withdrawalStatus") not in (None, "0"):
                continue
            sub = r.get("submitDateTime") or ""
            if sc not in found or sub > found[sc][1]:
                found[sc] = (r["docID"], sub)
        d += timedelta(days=1)
    print(f"offset {years}y: found {len(found)}/{len(metas)}", flush=True)
    return {sc: v[0] for sc, v in found.items()}


def collect(code: str, offset: int, doc_id: str) -> dict:
    rows = []
    period_end = None
    for _n, row in _iter_csv_rows(_ensure_csv_zip(doc_id)):
        el = (row.get("要素ID") or "").strip()
        ctx = (row.get("コンテキストID") or "").strip()
        val = (row.get("値") or "").strip()
        if not val or not KEEP.search(el):
            continue
        if el.endswith("CurrentFiscalYearEndDateDEI"):
            period_end = val
            continue
        if WANT.search(el) and CTX.match(ctx):
            rows.append([el, ctx, val[:60]])
    shutil.rmtree(ROOT / "cache" / "docs" / doc_id, ignore_errors=True)
    return {"code": code, "offset": offset, "doc_id": doc_id, "period_end": period_end, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offsets", type=int, nargs="+", default=[0, 5, 10])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    metas = []
    for p in sorted(DATA.glob("*/meta.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        if m.get("period_end") and m.get("seccode"):
            metas.append({"code": p.parent.name, **m})
    if a.limit:
        metas = metas[: a.limit]
    by_sec = {m["seccode"]: m["code"] for m in metas}

    jobs = []
    for off in a.offsets:
        if off == 0:
            jobs += [(m["code"], 0, m["doc_id"]) for m in metas]
        else:
            jobs += [(by_sec[sc], off, doc) for sc, doc in find_old_docs(metas, off).items()]

    dest = OUT / "history.jsonl.gz"
    failures = []
    done = 0
    with gzip.open(dest, "wt", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(collect, *j): j for j in jobs}
        for fut in as_completed(futs):
            try:
                fh.write(json.dumps(fut.result(), ensure_ascii=False) + "\n")
            except BaseException as err:  # SystemExit も拾う
                failures.append([*futs[fut], str(err)[:200]])
            done += 1
            if done % 500 == 0:
                print(f"{done}/{len(jobs)} failures={len(failures)}", flush=True)
    (OUT / "history_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=1))
    print(f"done {done} failures={len(failures)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
