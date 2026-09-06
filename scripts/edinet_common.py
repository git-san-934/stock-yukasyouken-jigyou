"""EDINET API v2 の共通処理。

- API キーは環境変数 EDINET_API_KEY もしくはリポジトリ直下の .env から読む。
- 書類一覧のレスポンスは cache/doclist/ に日付単位でキャッシュする
  （同じ日を何度も取りに行かないため）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
DATA = ROOT / "data"

# 有価証券報告書
DOC_TYPE_YUHO = "120"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_api_key() -> str:
    _load_dotenv()
    key = os.environ.get("EDINET_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "EDINET_API_KEY が未設定です。.env に EDINET_API_KEY=... を書くか、"
            "環境変数で渡してください。"
        )
    return key


def _get(url: str, params: dict, *, stream: bool = False) -> requests.Response:
    params = dict(params)
    params["Subscription-Key"] = get_api_key()
    resp = requests.get(url, params=params, stream=stream, timeout=60)
    resp.raise_for_status()
    return resp


def get_doc_list(date_str: str, *, use_cache: bool = True) -> dict:
    """指定日 (YYYY-MM-DD) の提出書類一覧を返す。"""
    cache_file = CACHE / "doclist" / f"{date_str}.json"
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    resp = _get(f"{API_BASE}/documents.json", {"date": date_str, "type": 2})
    payload = resp.json()

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    time.sleep(0.2)  # EDINET へ礼儀としての小休止
    return payload


def download_document(doc_id: str, doc_type: int, dest: Path) -> Path:
    """書類取得API。doc_type: 1=XBRL等ZIP, 2=PDF, 5=CSV(ZIP)。"""
    resp = _get(f"{API_BASE}/documents/{doc_id}", {"type": doc_type}, stream=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            fh.write(chunk)
    return dest
