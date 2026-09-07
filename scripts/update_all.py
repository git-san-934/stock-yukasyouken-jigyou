"""事業の内容をまとめて更新する。

  python scripts/update_all.py --all              # 全提出者（推奨）
  python scripts/update_all.py --all --limit 300  # 300 社だけ（分割実行）
  python scripts/update_all.py                    # companies.txt の銘柄だけ

--all は list_targets.py で EDINET から対象銘柄を自動収集する
（直近 --days 日に有価証券報告書を出し、証券コードを持つ提出者すべて）。
companies.txt はこのモードでは「除外リスト」として使う（コード頭に - を付けた行）。

既に data/<コード>/meta.json があり docID が同じ銘柄はスキップするので、
途中で止めても再実行すれば続きから進む。失敗した銘柄は cache/_failures.json に残す。

そのあと site/build.py を実行するとサイトに反映される。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from edinet_common import CACHE
from find_doc import normalize_seccode
from list_targets import TARGETS_FILE, harvest
from run_pipeline import run, run_doc

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FAILURES_FILE = CACHE / "_failures.json"
INCREMENTAL_DAYS = 90


def read_companies_txt() -> tuple[list[str], set[str]]:
    """(対象コード, 除外コード) を返す。行頭 - は除外指定。"""
    include, exclude = [], set()
    path = ROOT / "companies.txt"
    if not path.exists():
        return include, exclude
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            exclude.add(_short(line[1:].strip()))
        else:
            include.append(line)
    return include, exclude


def _short(code: str) -> str:
    code = normalize_seccode(code)
    return code[:-1] if len(code) == 5 else code


def has_data(code: str) -> bool:
    return (DATA / _short(code) / "meta.json").exists()


def load_targets(days: int, refresh: int, use_cached_manifest: bool) -> list[dict]:
    if use_cached_manifest and TARGETS_FILE.exists():
        print(f"既存のマニフェスト {TARGETS_FILE} を使用")
        return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    print("EDINET から対象銘柄を収集中…")
    targets = harvest(days=days, refresh=refresh)
    TARGETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TARGETS_FILE.write_text(
        json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")
    return targets


def run_all(args) -> list[str]:
    _, exclude = read_companies_txt()
    targets = load_targets(args.days, args.refresh, args.use_cached_manifest)
    targets = [t for t in targets if t["seccode"] not in exclude]

    if args.retry_failed:
        prev = set(json.loads(FAILURES_FILE.read_text(encoding="utf-8"))) \
            if FAILURES_FILE.exists() else set()
        targets = [t for t in targets if t["seccode"] in prev]
        print(f"前回失敗した {len(targets)} 社だけ再試行します")

    targets = targets[args.offset:]
    if args.limit:
        targets = targets[: args.limit]

    total = len(targets)
    print(f"対象 {total} 社（除外 {len(exclude)} 社、offset {args.offset}）")
    failed = []
    for i, t in enumerate(targets, 1):
        code, doc_id = t["seccode"], t["doc_id"]
        tag = f"[{i}/{total}] {code} {t['filer_name']}"
        try:
            result = run_doc(code, doc_id, drop_csv=args.drop_csv)
            print(f"{tag}  {'更新' if result else 'skip'}")
        except KeyboardInterrupt:
            raise
        except (SystemExit, Exception) as err:  # 1 社の異常でバッチを止めない
            print(f"{tag}  !! 失敗: {type(err).__name__}: {err}")
            failed.append(code)
        if args.sleep:
            time.sleep(args.sleep)
    return failed


def run_companies_txt(args) -> list[str]:
    codes, _ = read_companies_txt()
    print(f"対象 {len(codes)} 銘柄: {', '.join(codes)}")
    failed = []
    for code in codes:
        days = args.days if (args.full or not has_data(code)) else INCREMENTAL_DAYS
        print(f"\n=== {code} (遡及 {days} 日) ===")
        try:
            run(code, days=days)
        except SystemExit as err:
            print(f"!! {code} 失敗: {err}")
            failed.append(code)
    return failed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="companies.txt ではなく EDINET の全提出者を対象にする")
    ap.add_argument("--days", type=int, default=500, help="遡及日数")
    ap.add_argument("--refresh", type=int, default=7,
                    help="--all: 直近何日をキャッシュ無視で取り直すか")
    ap.add_argument("--full", action="store_true",
                    help="companies.txt モード: 既存銘柄もフルスキャン")
    ap.add_argument("--limit", type=int, default=0, help="--all: 先頭 N 社だけ処理")
    ap.add_argument("--offset", type=int, default=0, help="--all: 先頭 N 社を飛ばす")
    ap.add_argument("--drop-csv", action="store_true",
                    help="抽出後に CSV キャッシュを削除（ディスク節約）")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="1 社ごとの待ち秒数")
    ap.add_argument("--use-cached-manifest", action="store_true",
                    help="--all: cache/_targets.json があれば再収集しない")
    ap.add_argument("--retry-failed", action="store_true",
                    help="--all: cache/_failures.json の銘柄だけ再試行する")
    args = ap.parse_args()

    failed = run_all(args) if args.all else run_companies_txt(args)

    if failed:
        FAILURES_FILE.parent.mkdir(parents=True, exist_ok=True)
        FAILURES_FILE.write_text(
            json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n失敗 {len(failed)} 社（{FAILURES_FILE} に記録）: {', '.join(failed)}")
    else:
        print("\n全銘柄 完了")
