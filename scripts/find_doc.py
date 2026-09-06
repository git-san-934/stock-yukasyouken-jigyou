"""指定した証券コードの「有価証券報告書」を新しい順に列挙する。

EDINET API v2 の書類一覧 (documents.json) は日付単位でしか引けないため、
当日からさかのぼって走査する。各日のレスポンスは edinet_common でキャッシュ。
documents.json の各レコードには secCode(5桁) が入っているので、
EDINET コードへの変換なしで直接絞り込める。
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from edinet_common import DOC_TYPE_YUHO, get_doc_list


def normalize_seccode(code: str) -> str:
    code = code.strip().upper()
    return code + "0" if len(code) == 4 else code


def list_yuho(seccode: str, *, days: int = 500) -> list[dict]:
    target = normalize_seccode(seccode)
    today = date.today()
    hits: list[dict] = []
    for offset in range(days + 1):
        d = today - timedelta(days=offset)
        payload = get_doc_list(d.isoformat())
        for row in payload.get("results") or []:
            if (row.get("secCode") or "") != target:
                continue
            if row.get("docTypeCode") != DOC_TYPE_YUHO:
                continue
            hits.append(row)
    hits.sort(key=lambda r: r.get("submitDateTime") or "", reverse=True)
    return hits


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seccode")
    ap.add_argument("--days", type=int, default=500)
    args = ap.parse_args()

    docs = list_yuho(args.seccode, days=args.days)
    if not docs:
        raise SystemExit("有価証券報告書が見つかりませんでした。--days を増やして再試行してください。")
    for doc in docs:
        print(
            f"{doc.get('submitDateTime')}  {doc.get('docID')}  "
            f"{doc.get('docDescription')}  ({doc.get('periodStart')}〜{doc.get('periodEnd')})"
        )
