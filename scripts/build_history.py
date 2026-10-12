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
EPS_ELEMENTS = [
    "jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults",
    "jpcrp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",
    "jpcrp_cor:BasicEarningsLossPerShareUSGAAPSummaryOfBusinessResults",
]
DPS = "jpcrp_cor:DividendPaidPerShareSummaryOfBusinessResults"
IDPS = "jpcrp_cor:InterimDividendPaidPerShareSummaryOfBusinessResults"
CTX = re.compile(r"^(CurrentYear|Prior([1-4])Year)(Instant|Duration)(_NonConsolidatedMember)?$")


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
    """1つの有報から {期末(YYYY-MM): BPS}、当期末の発行済株式数、同じく EPS・1株配当 を返す"""
    pe = rec.get("period_end")
    if not pe:
        return None, {}, None, {}, {}
    pe = date.fromisoformat(pe[:10])
    eps = {False: {}, True: {}}
    dps = {False: {}, True: {}}
    idps = {False: {}, True: {}}
    vals = {False: {}, True: {}}  # nonconsolidated?
    shares = {False: {}, True: {}}  # 期ごとの発行済株式数（その時点の実数）
    for el, ctx, v in rec["rows"]:
        m = CTX.match(ctx)
        if not m:
            continue
        k = int(m.group(2) or 0)
        inst = m.group(3) == "Instant"
        nc = bool(m.group(4))
        x = _num(v)
        if x is None:
            continue
        if el in BPS_ELEMENTS and inst and x > 0:
            vals[nc].setdefault(k, x)
        elif el == SHARES and inst:
            shares[nc][k] = x
        elif el in EPS_ELEMENTS and not inst:
            eps[nc].setdefault(k, x)
        elif el == DPS and not inst:
            dps[nc].setdefault(k, x)
        elif el == IDPS and not inst:
            idps[nc].setdefault(k, x)
    use_nc = not vals[False]
    series, sh = vals[use_nc], shares[use_nc] or shares[not use_nc]
    cur = sh.get(0)
    # 同じ有報の中でも、分割前の期のBPSを直していない会社がある（例: IFRSで最古期だけ分割前）。
    # その期の株数が今と分割倍率ぶん違い、BPSも1期新しい値からその倍率近く跳ねていれば直す。
    out = {}
    intra = {}  # 期ごとに直した倍率（EPS・配当にも同じ倍率を使う）
    newer = None
    for k in sorted(series):
        x = series[k]
        if cur and sh.get(k) and newer:
            f = _snap(cur / sh[k])
            if f != 1.0 and abs(math.log(x / newer / f)) < abs(math.log(x / newer)):
                x /= f
                intra[k] = f
        out[f"{pe.year - k:04d}-{pe.month:02d}"] = x
        newer = x
    key = lambda k: f"{pe.year - k:04d}-{pe.month:02d}"
    e = eps[False] or eps[True]
    dv = dps[False] or dps[True]
    eo = {key(k): v / intra.get(k, 1.0) for k, v in e.items()}
    # 配当はEPS・BPSと違って分割で過去分を直さない（実際に払った額）ので、株数で直すために株数も返す
    iv = idps[False] or idps[True]
    do = {key(k): (v, iv.get(k), sh.get(k)) for k, v in dv.items()}
    return pe, out, cur, eo, do


def _adjust_dps(raw: dict[str, tuple]) -> dict[str, float]:
    """1株配当を最新期の株数ベースに直す。
    有報の配当は分割で過去分を直している会社と直していない会社が混在する（同じ有報の中でも混在する）。
    そこで新しい期から順にさかのぼり、隣り合う期の発行済株式数の比から分割を見つけたら「未消化の倍率」として持ち、
    配当がその倍率ぶん跳ねた所で直す。期中に分割した期は、中間配当（分割前）を直した値も試す。"""
    keys = sorted(raw)
    if not keys:
        return {}
    out = {keys[-1]: raw[keys[-1]][0]}
    cum, pending = 1.0, 1.0
    kn = keys[-1]
    for k in reversed(keys[:-1]):
        x, _, sh = raw[k]
        shn = raw[kn][2]
        if sh and shn:
            pending *= _snap(shn / sh)
        y = out[kn]
        if pending != 1.0 and x > 0 and y > 0:
            j = x / cum / y
            if abs(math.log(j / pending)) < 0.45:
                cum *= pending
                pending = 1.0
            else:
                yraw, yint, _ = raw[kn]
                if yint and 0 < yint <= yraw:
                    alt = (yint / pending + (yraw - yint)) / cum  # 1期新しい期が期中分割だった場合
                    if alt > 0 and abs(math.log(x / cum / alt / pending)) < 0.45:
                        out[kn] = alt
                        cum *= pending
                        pending = 1.0
        out[k] = x / cum
        kn = k
    return out


def _tail(m: dict[str, float]) -> list[str]:
    """最新期から1年ずつ途切れずに続いている期（古い順）"""
    keys = sorted(m)
    if not keys:
        return []
    out = [keys[-1]]
    for k in reversed(keys[:-1]):
        y1, m1 = map(int, out[0].split("-"))
        y0, m0 = map(int, k.split("-"))
        if not 6 <= (y1 - y0) * 12 + (m1 - m0) <= 15:
            break
        out.insert(0, k)
    return out


def build(path: Path) -> dict[str, dict]:
    docs = defaultdict(list)
    for line in gzip.open(path, "rt", encoding="utf-8"):
        rec = json.loads(line)
        pe, series, shares, eps, dps = _doc_series(rec)
        if pe and series:
            docs[rec["code"]].append((pe, series, shares, eps, dps))

    out = {}
    for code, items in docs.items():
        items.sort(key=lambda t: t[0], reverse=True)  # 新しい有報から
        merged: dict[str, float] = {}
        base_shares = items[0][2]
        m_eps: dict[str, float] = {}
        m_dps: dict[str, float] = {}
        notes = []
        prev_f = 1.0
        for pe, series, shares, eps, dps in items:
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
            for k, v in eps.items():
                m_eps.setdefault(k, v / f)
            for k, v in dps.items():
                m_dps.setdefault(k, v)
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
        m_dps = _adjust_dps(m_dps)
        e10, d10 = _tail(m_eps), _tail(m_dps)
        extra = {}
        if len(e10) >= 10:
            e10 = e10[-10:]
            ev = [m_eps[k] for k in e10]
            extra["eps10_pos"] = int(all(v > 0 for v in ev))
            extra["eps10_x"] = ev[-1] / ev[0] if ev[0] > 0 else None
        if len(d10) >= 10:
            d10 = d10[-10:]
            dv = [m_dps[k] for k in d10]
            extra["dps10_zero"] = sum(v <= 0 for v in dv)
            # 分割調整の端数で下がって見えないよう、2%未満の減少は減配としない
            extra["dps10_cut"] = sum(b < a * 0.98 for a, b in zip(dv, dv[1:]))
        r2 = (extra.get("eps10_pos") == 1 and (extra.get("eps10_x") or 0) >= 2 and streak >= 9
              and extra.get("dps10_zero") == 0 and extra.get("dps10_cut", 9) <= 1)
        extra["ricky2"] = int(r2) if len(e10) >= 10 and len(d10) >= 10 else None
        extra["eps_hist"] = " / ".join(f"{k[:4]}.{k[5:]}:{m_eps[k]:,.1f}" for k in sorted(m_eps))
        extra["dps_hist"] = " / ".join(f"{k[:4]}.{k[5:]}:{m_dps[k]:,.1f}" for k in sorted(m_dps))
        out[code] = {
            "bps_streak": streak,
            "bps_periods": len(keys),
            "bps_from": first,
            "bps_growth": merged[last] / merged[first] if merged[first] > 0 else None,
            "bps_hist": " / ".join(f"{k[:4]}.{k[5:]}:{merged[k]:,.0f}" for k in keys),
            "bps_note": "、".join(notes),
            **extra,
        }
    return out


if __name__ == "__main__":
    import sys
    res = build(Path(sys.argv[1]))
    for code in list(res)[:10]:
        print(code, res[code])
