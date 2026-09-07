"""EDINET の書類一覧をさかのぼり、有価証券報告書を出した提出者を全部集める。

  python scripts/list_targets.py [--days 500] [--refresh 7]

companies.txt を手で育てる代わりに、これで対象銘柄リストを自動生成する。
docTypeCode=120（有価証券報告書）かつ secCode を持つレコードを拾い、
証券コード単位で最新の提出を 1 件に絞って cache/_targets.json に書き出す。

各日のレスポンスは edinet_common がキャッシュする（501 日分で数百リクエスト）。
直近 --refresh 日はキャッシュを無視して取り直す（当日ぶんは後から追記されるため）。
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from edinet_common import CACHE, DOC_TYPE_YUHO, get_doc_list

TARGETS_FILE = CACHE / "_targets.json"


def normalize_seccode(code: str) -> str:
    code = code.strip().upper()
    return code + "0" if len(code) == 4 else code


def short_seccode(code: str) -> str:
    code = normalize_seccode(code)
    return code[:-1] if len(code) == 5 else code


def harvest(days: int = 500, refresh: int = 7) -> list[dict]:
    today = date.today()
    by_code: dict[str, dict] = {}
    for offset in range(days + 1):
        d = today - timedelta(days=offset)
        payload = get_doc_list(d.isoformat(), use_cache=offset >= refresh)
        for row in payload.get("results") or []:
            sec = (row.get("secCode") or "").strip()
            if not sec or row.get("docTypeCode") != DOC_TYPE_YUHO:
                continue
            submitted = row.get("submitDateTime") or ""
            cur = by_code.get(sec)
            if cur and (cur.get("submitDateTime") or "") >= submitted:
                continue
            by_code[sec] = {
                "seccode": short_seccode(sec),
                "seccode5": normalize_seccode(sec),
                "doc_id": row.get("docID"),
                "filer_name": row.get("filerName") or "",
                "submitDateTime": submitted,
                "period_start": row.get("periodStart") or "",
                "period_end": row.get("periodEnd") or "",
                "doc_description": row.get("docDescription") or "",
            }
    targets = sorted(by_code.values(), key=lambda r: r["seccode"])
    return targets


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=500, help="遡及日数")
    ap.add_argument("--refresh", type=int, default=7,
                    help="直近何日ぶんをキャッシュ無視で取り直すか")
    args = ap.parse_args()

    targets = harvest(days=args.days, refresh=args.refresh)
    TARGETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TARGETS_FILE.write_text(
        json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"対象 {len(targets)} 社を {TARGETS_FILE} に書き出しました。")
