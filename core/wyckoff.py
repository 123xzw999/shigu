# -*- coding: utf-8 -*-
"""
主力行为识别 · wyckoff.py
=========================
把威科夫（Wyckoff）量价周期搬到 A 股，用可量化的特征识别主力所处阶段：

    吸筹 (Accumulation) → 洗盘 (Shakeout) → 拉升 (Markup)
                                            ↓
    下跌 (Markdown)   ← 派发 (Distribution)

每个阶段用一组软打分（sigmoid / tanh）计算置信度，再用 softmax 归一化，
避免硬阈值导致阶段频繁跳变。

同时提供 `segment_phases()`：把历史行情切成阶段片段，并算出
**每个阶段的成交量加权均价（VWAP）**——这就是「该阶段主力筹码成本」。
"""

import math

from . import indicators as ta


def _sig(x):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _pct(a, b):
    return (a - b) / b * 100 if b else 0.0


def _features(bars, idx):
    """在 idx 处提取量价特征"""
    close = [b["close"] for b in bars]
    high = [b["high"] for b in bars]
    low = [b["low"] for b in bars]
    vol = [b["volume"] for b in bars]

    n = idx + 1
    w60 = bars[max(0, idx - 59):idx + 1]
    l60 = min(x["low"] for x in w60)
    h60 = max(x["high"] for x in w60)
    p60 = (close[idx] - l60) / (h60 - l60) if h60 > l60 else 0.5

    w250 = bars[max(0, idx - 249):idx + 1]
    l250 = min(x["low"] for x in w250)
    h250 = max(x["high"] for x in w250)
    p250 = (close[idx] - l250) / (h250 - l250) if h250 > l250 else 0.5

    def avg_amp(k):
        w = bars[max(0, idx - k + 1):idx + 1]
        return sum((x["high"] - x["low"]) / x["close"] * 100 for x in w if x["close"]) / max(len(w), 1)

    amp10 = avg_amp(10)
    amp60 = avg_amp(60)
    amp_ratio = amp10 / amp60 if amp60 > 0 else 1.0

    def vmean(k, off=0):
        s = max(0, idx - off - k + 1)
        e = idx - off + 1
        w = vol[s:e] if e > s else vol[-k:]
        return sum(w) / len(w) if w else 1.0

    v5 = vmean(5)
    v20 = vmean(20)
    v60 = vmean(60)
    vr5 = v5 / v20 if v20 else 1.0
    vr20 = v20 / v60 if v60 else 1.0

    def chg(k):
        if idx - k < 0:
            return 0.0
        return _pct(close[idx], close[idx - k])

    chg5, chg20, chg60 = chg(5), chg(20), chg(60)

    # 均线排列
    ma5 = sum(close[max(0, idx - 4):idx + 1]) / min(5, n)
    ma20 = sum(close[max(0, idx - 19):idx + 1]) / min(20, n)
    ma60 = sum(close[max(0, idx - 59):idx + 1]) / min(60, n)
    align = 0.0
    if ma5 > ma20:
        align += 0.5
    if ma20 > ma60:
        align += 0.5
    if ma5 < ma20:
        align -= 0.5
    if ma20 < ma60:
        align -= 0.5

    # 上下影线占比（近 10 日）
    w = bars[max(0, idx - 9):idx + 1]
    us = sum(max(0, x["high"] - max(x["close"], x["open"])) for x in w)
    ds = sum(max(0, min(x["close"], x["open"]) - x["low"]) for x in w)
    tot_sh = us + ds
    us_ratio = us / tot_sh if tot_sh > 0 else 0.5

    # OBV 斜率
    obv = ta.obv(close[:idx + 1], vol[:idx + 1])
    obv_slope = 0.0
    if len(obv) >= 20 and obv[-20] is not None and obv[-1] is not None:
        base = abs(obv[-20]) if obv[-20] else 1.0
        obv_slope = (obv[-1] - obv[-20]) / max(base, 1.0)

    # 近 5 日最大单日跌幅 / 单日最大涨幅
    recent = bars[max(0, idx - 4):idx + 1]
    max_drop = min((_pct(x["close"], x["open"]) for x in recent), default=0.0)
    max_rise = max((_pct(x["close"], x["open"]) for x in recent), default=0.0)

    # 收盘位置（近5日，收盘在当日区间的位置均值）
    close_pos = sum(((x["close"] - x["low"]) / (x["high"] - x["low"])
                     if x["high"] > x["low"] else 0.5) for x in recent) / max(len(recent), 1)

    return {
        "p60": p60, "p250": p250,
        "amp10": amp10, "amp60": amp60, "amp_ratio": amp_ratio,
        "vr5": vr5, "vr20": vr20,
        "chg5": chg5, "chg20": chg20, "chg60": chg60,
        "align": align, "us_ratio": us_ratio, "obv_slope": obv_slope,
        "max_drop": max_drop, "max_rise": max_rise, "close_pos": close_pos,
        "vol_trend": v5 / v20 if v20 else 1.0,
    }


def _scores(f):
    """各阶段原始得分（未归一化）"""
    # 吸筹：低位 + 振幅收敛 + 缩量 + 下影多 + OBV 不跌
    acc = (2.6 * (0.42 - f["p60"])
           + 1.8 * (1.0 - min(f["amp_ratio"], 1.6))
           + 1.2 * (1.0 - min(f["vr20"], 1.6))
           + 1.4 * (f["us_ratio"] * -1 + 0.5) * 1.2
           + 1.0 * max(0.0, f["obv_slope"] * 3)
           - 0.6 * max(0.0, f["chg20"] / 10))

    # 洗盘：中低位 + 单日急跌 + 收盘位置高（下探回升）+ 量能先放后缩
    shake = (1.6 * (0.55 - abs(f["p60"] - 0.38) * 2.2)
             + 2.0 * min(1.0, max(0.0, -f["max_drop"] / 4.0))
             + 1.6 * (f["close_pos"] - 0.45)
             + 1.2 * (1.0 if 0.85 < f["vr5"] < 2.2 else 0.0)
             + 0.8 * (f["amp_ratio"] - 0.9))

    # 拉升：中高位 + 放量上涨 + 均线多头 + OBV 上行
    mark = (1.8 * (f["p60"] - 0.5) * 2
            + 2.0 * min(1.5, max(-0.5, f["chg20"] / 12.0))
            + 1.6 * f["align"]
            + 1.2 * max(0.0, min(1.0, f["vr5"] - 0.9))
            + 1.0 * max(0.0, min(1.0, f["obv_slope"] * 4)))

    # 派发：高位 + 放量滞涨 + 上影多 + 振幅扩大
    dist = (2.2 * (f["p60"] - 0.6) * 2
            + 1.8 * max(0.0, min(1.2, f["vr20"] - 1.1))
            + 1.6 * (f["us_ratio"] - 0.45) * 1.6
            + 1.0 * max(0.0, f["amp_ratio"] - 1.05)
            - 1.4 * max(0.0, f["chg20"] / 10))

    # 下跌：高位回落 + 均线空头 + 持续阴跌
    down = (2.0 * max(0.0, -f["chg20"] / 10)
            + 1.8 * max(0.0, -f["chg60"] / 18)
            - 1.6 * f["align"]
            + 1.0 * max(0.0, 0.5 - f["p60"]) * 0.6
            + 0.8 * max(0.0, -f["obv_slope"] * 3))

    # 横盘：振幅极小 + 涨跌接近 0 + 量能平稳
    side = (2.4 * (1.0 - min(f["amp_ratio"], 1.5))
            + 2.0 * max(0.0, 1.0 - abs(f["chg20"]) / 6.0)
            + 1.2 * max(0.0, 1.0 - abs(f["vr20"] - 1.0) * 2))

    return {"吸筹": acc, "洗盘": shake, "拉升": mark, "派发": dist,
            "下跌": down, "横盘": side}


def current_phase(bars, idx=None):
    if not bars or len(bars) < 30:
        return {"phase": "数据不足", "confidence": 0.0, "detail": {}, "features": {}}
    idx = len(bars) - 1 if idx is None else idx
    f = _features(bars, idx)
    raw = _scores(f)
    # softmax
    mx = max(raw.values())
    ex = {k: math.exp(min(20.0, 1.55 * (v - mx))) for k, v in raw.items()}
    s = sum(ex.values())
    prob = {k: v / s for k, v in ex.items()}
    best = max(prob, key=prob.get)
    return {
        "phase": best,
        "confidence": round(prob[best], 3),
        "detail": {k: round(v, 3) for k, v in prob.items()},
        "features": {
            "位置(60日)": round(f["p60"] * 100, 1),
            "位置(250日)": round(f["p250"] * 100, 1),
            "振幅比(10/60)": round(f["amp_ratio"], 2),
            "量比(5/20)": round(f["vr5"], 2),
            "量能趋势(20/60)": round(f["vr20"], 2),
            "涨跌(5/20/60日)": [round(f["chg5"], 2), round(f["chg20"], 2), round(f["chg60"], 2)],
            "均线排列": round(f["align"], 1),
            "上影占比": round(f["us_ratio"] * 100, 1),
            "OBV斜率": round(f["obv_slope"], 4),
            "收盘位置": round(f["close_pos"], 2),
        },
    }


PHASE_DESC = {
    "吸筹": "主力在低位反复震荡收集筹码：振幅收敛、量能萎缩、下影线频繁，OBV 不再创新低。",
    "洗盘": "主力用急跌或长下影把浮筹震出：单日快速下探后当日收回，量能先放大后迅速萎缩。",
    "拉升": "主力已完成控盘并推动股价上行：放量突破、均线多头排列、OBV 同步走高。",
    "派发": "主力在高位借人气出货：放量滞涨、长上影频现、振幅扩大而股价不涨。",
    "下跌": "主力撤离后无人承接：均线空头排列、缩量阴跌、反弹无力。",
    "横盘": "多空暂时均衡：振幅极窄、涨跌接近零、量能平稳，等待方向选择。",
    "数据不足": "K线数量不足，无法判断主力阶段。",
}


def segment_phases(bars, step=5, span=260, min_len=8, max_seg=8):
    """
    把历史切成阶段片段，并给出每段的成交量加权均价（= 该阶段主力成本）。
    为控制开销，按 step 根采样判定阶段，再合并连续同阶段区间。
    """
    n = len(bars)
    if n < 80:
        return []
    start = max(30, n - span)
    marks = []
    i = start
    while i < n:
        marks.append((i, current_phase(bars[:i + 1])["phase"]))
        i += step
    if not marks or marks[-1][0] != n - 1:
        marks.append((n - 1, current_phase(bars)["phase"]))

    segs = []
    cur = None
    for i, lab in marks:
        if cur is None or lab != cur["phase"]:
            if cur:
                cur["end"] = prev_i
                segs.append(cur)
            cur = {"phase": lab, "start": i, "end": i}
        else:
            cur["end"] = i
        prev_i = i
    if cur:
        cur["end"] = n - 1
        segs.append(cur)

    merged = []
    for idx, s in enumerate(segs):
        is_last = (idx == len(segs) - 1)
        short = (s["end"] - s["start"] + 1) < min_len
        if merged and short and (not is_last or (s["end"] - s["start"] + 1) < 3):
            merged[-1]["end"] = s["end"]
        else:
            merged.append(s)

    out = []
    for s in merged[-max_seg:]:
        seg = bars[s["start"]:s["end"] + 1]
        vs = sum(b["volume"] for b in seg)
        vwap = (sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in seg) / vs
                if vs else seg[-1]["close"])
        out.append({
            "phase": s["phase"],
            "start": s["start"], "end": s["end"],
            "start_day": seg[0]["day"], "end_day": seg[-1]["day"],
            "vwap": round(vwap, 3),
            "low": round(min(b["low"] for b in seg), 3),
            "high": round(max(b["high"] for b in seg), 3),
            "volume": round(vs, 0),
            "chg_pct": round(_pct(seg[-1]["close"], seg[0]["open"]), 2),
            "days": len(seg),
        })
    return out
