"""companies.txt に並べた証券コードすべてについて事業の内容を更新する。

  python scripts/update_all.py [--days 500] [--full]

既に data/<コード>/ がある銘柄は直近だけを見に行く（既存の書類より新しい
有報が出ていなければ何もしない）。--full で全銘柄フルスキャン。

そのあと site/build.py を実行するとサイトに反映される
（GitHub Actions では続けて実行される）。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from find_doc import normalize_seccode
from run_pipeline import run

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INCREMENTAL_DAYS = 90


def read_codes() -> list[str]:
    codes = []
    for line in (ROOT / "companies.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            codes.append(line)
    return codes


def has_data(code: str) -> bool:
    short = normalize_seccode(code)
    short = short[:-1] if len(short) == 5 else short
    return (DATA / short / "meta.json").exists()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=500, help="初回スキャンの遡及日数")
    ap.add_argument("--full", action="store_true", help="既存銘柄もフルスキャン")
    args = ap.parse_args()

    codes = read_codes()
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
    if failed:
        raise SystemExit(f"失敗した銘柄: {', '.join(failed)}")
    print("\n全銘柄 完了")
