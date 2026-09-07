"""証券コードを 1 つ渡すと、事業の内容を data/<コード>/ に書き出すところまで通す。

  python scripts/run_pipeline.py 285A
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from extract_business import extract
from find_doc import list_yuho, normalize_seccode

DATA = Path(__file__).resolve().parent.parent / "data"


def _existing_doc_id(seccode: str) -> str | None:
    short = normalize_seccode(seccode)
    short = short[:-1] if len(short) == 5 else short
    meta = DATA / short / "meta.json"
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8")).get("doc_id")
    return None


def run_doc(seccode: str, doc_id: str, *, drop_csv: bool = False) -> dict | None:
    """docID を直接渡す版（書類一覧の再スキャンを省く）。list_targets 用。"""
    if _existing_doc_id(seccode) == doc_id:
        print(f"      {doc_id} は取得済み。更新なし。")
        return None
    result = extract(doc_id, drop_csv=drop_csv)
    print(f"      書き出し: {result['out_dir']}")
    return result


def run(seccode: str, *, days: int = 500, allow_no_update: bool = True) -> dict | None:
    known = _existing_doc_id(seccode)
    docs = list_yuho(seccode, days=days)

    if not docs:
        msg = f"過去 {days} 日に有価証券報告書が見つかりませんでした。"
        if known and allow_no_update:
            print(f"      {msg} 既存データを維持します。")
            return None
        raise SystemExit(msg + " --days を増やしてください。")

    if known and docs[0]["docID"] == known:
        print(f"      最新有報 {known} は取得済み。更新なし。")
        return None

    print(f"[1/2] 有報候補 {len(docs)} 件（新しい順）")
    last_err: Exception | None = None
    for doc in docs:
        print(f"      試行: {doc['docID']}  {doc.get('docDescription')}")
        try:
            result = extract(doc["docID"])
        except SystemExit as err:  # 事業の内容が無い訂正報告書などはスキップ
            last_err = err
            print(f"        -> スキップ ({err})")
            continue
        print(f"[2/2] 書き出し: {result['out_dir']}")
        return result

    raise SystemExit(f"事業の内容を含む有報が見つかりませんでした（最後のエラー: {last_err}）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seccode", help="証券コード（例: 285A / 7203）")
    ap.add_argument("--days", type=int, default=500)
    args = ap.parse_args()
    run(args.seccode, days=args.days)
