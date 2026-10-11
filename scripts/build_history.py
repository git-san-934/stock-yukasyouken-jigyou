"""screen/history.jsonl.gz（fetch_history.py の出力）から、銘柄ごとのBPSの推移と
「何期連続で増えているか」を計算する。build_screen.py から呼ぶ。

- 各有報の「主要な経営指標等の推移」の5期分をつなげる（同じ期は新しい有報の値を優先）。
- 連結の値があれば連結、なければ単体。
- 有報ごとに株式分割の前提が違うので、新しい有報と古い有報の発行済株式数の比から
  分割・併合を推定して古い有報のBPSを今の株数ベースに直す。
"""
from __future__ import annotations

import gzip
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

BPS_ELEMENTS = [
    "jpcrp_cor:NetAssetsPerShareSummaryOfBusinessResults",
    "jpcrp_cor:EquityToAssetRatioIFRSSummaryOfBusinessResults",  # IFRS: 1株当たり親会社所有者帰属持分
    "jpcrp_cor:EquityAttributableToOwnersOfParentPerShareUSGAAPSummaryOfBusinessResults",
]
SHARES = "jpcrp_cor:TotalNumberOfIssuedSharesSummaryOfBusinessResults"
FACTORS = (2, 3, 4, 5, 10, 20, 50, 100, 1.5, 1.2, 1.1)
# つなぎ目でBPSが跳ねた時に分割とみなす倍率（併合は逆数）
JUMPS = (1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 15, 20, 30, 40, 50, 100)
CTX = re.compile(r"^(CurrentYear|Prior([1-4])Year)Instant(_NonConsolidatedMember)?$")


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _snap(r: float) -> float:
    """発行済株式数の比を分割・併合の倍率に丸める（はっきりしない時は1）"""
    if 0.7 <= r <= 1.4:
        return 1.0
    inv = r < 1
    x = 1 / r if inv else r
    f = min(FACTORS, key=lambda f: abs(x / f - 1))
    if abs(x / f - 1) > 0.15:
        return 1.0
    return 1 / f if inv else f


def _jump_factor(j: float) -> float:
    """BPSの跳ね方 j が分割・併合の倍率に近ければその倍率、そうでなければ1"""
    if abs(math.log(j)) < math.log(1.6):
        return 1.0
    x = 1 / j if j < 1 else j
    f = min(JUMPS, key=lambda f: abs(math.log(x / f)))
    if abs(math.log(x / f)) > 0.12:
        return 1.0
    return 1 / f if j < 1 else f


def _doc_series(rec):
    """1つの有報から {期末(YYYY-MM): BPS} と当期末の発行済株式数を返す"""
    pe = rec.get("period_end")
    if not pe:
        return None, {}, None
    pe = date.fromisoformat(pe[:10])
    vals = {False: {}, True: {}}  # nonconsolidated?
    shares = {False: {}, True: {}}  # 期ごとの発行済株式数（その時点の実数）
    for el, ctx, v in rec["rows"]:
        m = CTX.match(ctx)
        if not m:
            continue
        k = int(m.group(2) or 0)
        nc = bool(m.group(3))
        x = _num(v)
        if x is None:
            continue
        if el in BPS_ELEMENTS and x > 0:
            vals[nc].setdefault(k, x)
        elif el == SHARES:
            shares[nc][k] = x
    use_nc = not vals[False]
    series, sh = vals[use_nc], shares[use_nc] or shares[not use_nc]
    cur = sh.get(0)
    # 同じ有報の中でも、分割前の期のBPSを直していない会社がある（例: IFRSで最古期だけ分割前）。
    # その期の株数が今と分割倍率ぶん違い、BPSも1期新しい値からその倍率近く跳ねていれば直す。
    out = {}
    newer = None
    for k in sorted(series):
        x = series[k]
        if cur and sh.get(k) and newer:
            f = _snap(cur / sh[k])
            if f != 1.0 and abs(math.log(x / newer / f)) < abs(math.log(x / newer)):
                x /= f
        out[f"{pe.year - k:04d}-{pe.month:02d}"] = x
        newer = x
    return pe, out, cur


def build(path: Path) -> dict[str, dict]:
    docs = defaultdict(list)
    for line in gzip.open(path, "rt", encoding="utf-8"):
        rec = json.loads(line)
        pe, series, shares = _doc_series(rec)
        if pe and series:
            docs[rec["code"]].append((pe, series, shares))

    out = {}
    for code, items in docs.items():
        items.sort(key=lambda t: t[0], reverse=True)  # 新しい有報から
        merged: dict[str, float] = {}
        base_shares = items[0][2]
        notes = []
        prev_f = 1.0
        for pe, series, shares in items:
            f = 1.0
            common = [k for k in series if k in merged]
            if common:
                # 期が重なっていれば、同じ期のBPSの比がそのまま分割の倍率
                rs = sorted(series[k] / merged[k] for k in common)
                f = _jump_factor(rs[len(rs) // 2])
            elif merged:
                # 重ならなければ、つなぎ目の跳ね方を見る。発行済株式数の比と合えばそれを使い、
                # 株数が当てにならない場合（決算期後の分割など）は跳ね方が分割倍率に近い時だけ直す
                j = series[max(series)] / merged[min(merged)]
                fs = _snap(base_shares / shares) if base_shares and shares else 1.0
                if fs != 1.0 and abs(math.log(j / fs)) < 0.3:
                    f = fs
                else:
                    f = _jump_factor(j)
            if f != prev_f:
                how = f"1株→{f:g}株の分割" if f > 1 else f"{1 / f:g}株→1株の併合"
                notes.append(f"{pe.year}年{pe.month}月期以前を{how}とみなして調整")
            prev_f = f
            for k, v in series.items():
                merged.setdefault(k, v / f)
        keys = sorted(merged)
        # 最新期から1年ずつさかのぼって、連続して増えている期数を数える
        streak = 0
        for i in range(len(keys) - 1, 0, -1):
            y1, m1 = map(int, keys[i].split("-"))
            y0, m0 = map(int, keys[i - 1].split("-"))
            months = (y1 - y0) * 12 + (m1 - m0)
            if not 6 <= months <= 15:  # 抜けている期があれば打ち切る
                break
            if merged[keys[i]] > merged[keys[i - 1]]:
                streak += 1
            else:
                break
        first, last = keys[0], keys[-1]
        out[code] = {
            "bps_streak": streak,
            "bps_periods": len(keys),
            "bps_from": first,
            "bps_growth": merged[last] / merged[first] if merged[first] > 0 else None,
            "bps_hist": " / ".join(f"{k[:4]}.{k[5:]}:{merged[k]:,.0f}" for k in keys),
            "bps_note": "、".join(notes),
        }
    return out


if __name__ == "__main__":
    import sys
    res = build(Path(sys.argv[1]))
    for code in list(res)[:10]:
        print(code, res[code])
