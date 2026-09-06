"""有価証券報告書 (docID 指定) から「事業の内容」を取り出す。

EDINET 書類取得API の CSV 形式 (type=5) を使う。CSV は UTF-16 / タブ区切りで、
要素ID 列が XBRL のタグ名になっている。「事業の内容」は
  jpcrp_cor:DescriptionOfBusinessTextBlock
に HTML 断片として入っている。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from pathlib import Path

from edinet_common import CACHE, DATA, download_document
from htmltext import html_to_text

# 抽出したい主なテキストブロック（要素ID -> 見出し）
TEXT_BLOCKS = {
    "jpcrp_cor:DescriptionOfBusinessTextBlock": "事業の内容",
}

# 会社名・会計期間を拾うための要素ID
META_ELEMENTS = {
    "jpdei_cor:FilerNameInJapaneseDEI": "filer_name",
    "jpdei_cor:FilerNameInEnglishDEI": "filer_name_en",
    "jpdei_cor:CurrentFiscalYearStartDateDEI": "period_start",
    "jpdei_cor:CurrentFiscalYearEndDateDEI": "period_end",
    "jpdei_cor:SecurityCodeDEI": "seccode",
    "jpdei_cor:EDINETCodeDEI": "edinet_code",
}


def _ensure_csv_zip(doc_id: str) -> Path:
    zip_path = CACHE / "docs" / doc_id / "csv.zip"
    if not zip_path.exists():
        download_document(doc_id, 5, zip_path)
    return zip_path


def _iter_csv_rows(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        for name in names:
            raw = zf.read(name)
            text = raw.decode("utf-16", errors="replace")
            reader = csv.DictReader(io.StringIO(text), delimiter="\t")
            for row in reader:
                yield name, row


def extract(doc_id: str) -> dict:
    zip_path = _ensure_csv_zip(doc_id)

    meta: dict[str, str] = {"doc_id": doc_id}
    blocks: dict[str, str] = {}

    for _name, row in _iter_csv_rows(zip_path):
        element = (row.get("要素ID") or "").strip()
        value = row.get("値") or ""

        if element in META_ELEMENTS and value.strip():
            meta.setdefault(META_ELEMENTS[element], value.strip())

        if element in TEXT_BLOCKS and value.strip() and element not in blocks:
            blocks[element] = html_to_text(value)

    if "jpcrp_cor:DescriptionOfBusinessTextBlock" not in blocks:
        raise SystemExit(
            "この書類の CSV に DescriptionOfBusinessTextBlock が見つかりませんでした。"
        )

    seccode = meta.get("seccode", "").strip()
    # SecurityCodeDEI は 5 桁。表示・ディレクトリ名は 4 桁に寄せる。
    short = seccode[:-1] if len(seccode) == 5 else seccode
    out_dir = DATA / (short or doc_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    business_md = out_dir / "business.md"
    business_md.write_text(
        f"# {meta.get('filer_name', '')} 事業の内容\n\n"
        f"> 出典: 有価証券報告書 (EDINET 書類ID {doc_id}) / "
        f"対象期間 {meta.get('period_start', '?')}〜{meta.get('period_end', '?')}\n\n"
        + blocks["jpcrp_cor:DescriptionOfBusinessTextBlock"],
        encoding="utf-8",
    )

    meta_json = out_dir / "meta.json"
    meta_json.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"out_dir": str(out_dir), "meta": meta}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id")
    args = ap.parse_args()
    result = extract(args.doc_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
