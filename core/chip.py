# -*- coding: utf-8 -*-
"""
筹码分布引擎 · chip.py  (CYQ / Cost of Your Qímǎ)
=================================================
核心思想：把「历史成交量」按当日价格区间铺开，再按换手率衰减，
得到一张「价格 → 持仓量」的分布图。这是判断主力成本区 / 散户套牢区的地基。

模型
----
1. 价格网格离散化：把 [最低价, 最高价] 切成 N 档（默认 220）。

2. 单日筹码分布 —— 三角分布（Triangular Distribution）：
   当日的成交不会均匀落在 [low, high] 上，而是集中在均价附近。
   设当日均价 a = (H+L+C)/3，密度函数
        f(x) = 2(x-L) / ((H-L)(a-L))        L ≤ x ≤ a
        f(x) = 2(H-x) / ((H-L)(H-a))        a < x ≤ H
   这比均匀分布更贴近真实成交结构（越靠近均价成交越密集）。

3. 换手衰减：
        A_t = A_{t-1} · (1 - k · T_t) + V_t · φ_t(x)
   T_t 为当日换手率，k 为衰减系数（config.CHIP_DECAY_K）。
   含义：换手越充分，历史筹码被替换得越彻底。

4. 主力 / 散户双层：
   把每日的「换手筹码」拆成两层，拆分比例由当日主力参与度决定：
        m_t = 0.5 + 0.42 · tanh( 0.9(vr_t - 1) + 6·r_t + 0.35(0.5 - p_t) )
   其中 vr_t = 量比，r_t = 当日涨跌幅(小数)，p_t = 60日价格分位(0=底部, 1=顶部)。
   —— 放量 + 上涨 + 低位 → 主力吸筹占比高；放量 + 下跌 + 高位 → 主力派发。
   两层各自独立衰减：
        主力:  A^m_t = A^m_{t-1}(1 - k·T_t·m_t) + V_t·m_t·φ_t(x)
        散户:  A^s_t = A^s_{t-1}(1 - k·T_t·(1-m_t)) + V_t·(1-m_t)·φ_t(x)

5. 派生指标：主力成本、散户成本、获利盘、90%成本区间、集中度、
   主力筹码集中区、散户筹码集中区、控盘度、套牢盘、筹码迁移速度。
"""

import math

from . import config


# ------------------------------------------------------------ 工具

def _tri_weights(lo, hi, avg, centers, step, sharp=1.0):
    """
    三角分布权重（已归一化，使 sum(w)*step ≈ 1）。
    sharp > 1 峰值更尖（大单集中在均价成交）；sharp < 1 更平坦（小单追价，铺满区间）。
    主力与散户用不同的 sharp —— 这是两层筹码能在「价格上」分开的关键。
    """
    n = len(centers)
    w = [0.0] * n
    if hi <= lo:
        idx = int(round((lo - centers[0]) / step)) if step else 0
        idx = max(0, min(n - 1, idx))
        w[idx] = 1.0 / step
        return w
    a = min(max(avg, lo + (hi - lo) * 0.001), hi - (hi - lo) * 0.001)
    for i, c in enumerate(centers):
        if c < lo or c > hi:
            continue
        if c <= a:
            w[i] = 2.0 * (c - lo) / ((hi - lo) * (a - lo))
        else:
            w[i] = 2.0 * (hi - c) / ((hi - lo) * (hi - a))
    if sharp != 1.0:
        w = [x ** sharp for x in w]
    s = sum(w) * step
    if s > 0:
        w = [x / s for x in w]
    return w


def _weighted_quantile(centers, weights, q):
    tot = sum(weights)
    if tot <= 0:
        return centers[len(centers) // 2] if centers else 0.0
    target = tot * q
    acc = 0.0
    for c, w in zip(centers, weights):
        acc += w
        if acc >= target:
            return c
    return centers[-1]


def _weighted_mean(centers, weights):
    tot = sum(weights)
    if tot <= 0:
        return 0.0
    return sum(c * w for c, w in zip(centers, weights)) / tot


def _peak_zone(centers, weights, cover=0.60, min_width_bins=2):
    """
    从分布最高峰向两侧扩展，直到累计覆盖 cover 比例，返回 (lo, hi, peak_price)。
    这是「主力/散户筹码集中区」的核心识别函数。
    """
    if not weights or sum(weights) <= 0:
        return None
    tot = sum(weights)
    pk = max(range(len(weights)), key=lambda i: weights[i])
    target = tot * cover
    acc = weights[pk]
    left = right = pk
    while acc < target and (left > 0 or right < len(weights) - 1):
        wl = weights[left - 1] if left > 0 else -1
        wr = weights[right + 1] if right < len(weights) - 1 else -1
        if wr >= wl:
            right += 1
            acc += max(wr, 0)
        else:
            left -= 1
            acc += max(wl, 0)
    if right - left < min_width_bins:
        right = min(len(weights) - 1, left + min_width_bins)
    return centers[left], centers[right], centers[pk]


def _find_peaks(centers, weights, top=3, rel=0.35):
    """局部极大值（筹码峰）。rel 为相对最高峰的阈值。"""
    if not weights:
        return []
    mx = max(weights)
    if mx <= 0:
        return []
    peaks = []
    for i in range(1, len(weights) - 1):
        if weights[i] >= weights[i - 1] and weights[i] >= weights[i + 1] and weights[i] > mx * rel:
            peaks.append((centers[i], weights[i]))
    peaks.sort(key=lambda x: -x[1])
    return [{"price": round(p, 3), "weight": round(w / mx, 4)} for p, w in peaks[:top]]


# ------------------------------------------------------------ 成交量分布（Volume Profile）

def volume_profile(bars, bins=140, va_ratio=0.70, max_days=250):
    """
    Volume Profile / TPO —— 参照 srl-python-indicators 的 Volume Profile 思路。

    与 CYQ 的区别（两者互补，不是重复）：
      * CYQ（上面那个 analyze）：带换手衰减的「当前持仓成本分布」——
        回答「现在谁在什么价位还拿着筹码」。
      * Volume Profile（本函数）：不衰减的「历史成交密集区」——
        回答「过去一年资金在哪个价位反复换手」。

    POC (Point of Control)  = 成交量最大的价位，最公认的价值中枢
    VAH / VAL (Value Area)  = 覆盖 va_ratio 成交量的价格带上下沿
    """
    if not bars or len(bars) < 20:
        return None
    data = bars[-max_days:]
    lo = min(b["low"] for b in data)
    hi = max(b["high"] for b in data)
    if hi <= lo:
        hi = lo * 1.01
    step = (hi - lo) / bins
    centers = [lo + step * (i + 0.5) for i in range(bins)]

    prof = [0.0] * bins
    for b in data:
        avg = (b["high"] + b["low"] + b["close"]) / 3.0
        phi = _tri_weights(b["low"], b["high"], avg, centers, step, 1.0)
        v = b["volume"]
        if v <= 0:
            continue
        for j in range(bins):
            prof[j] += v * phi[j]

    total = sum(prof)
    if total <= 0:
        return None

    poc_i = max(range(bins), key=lambda i: prof[i])
    target = total * va_ratio
    acc = prof[poc_i]
    l = r = poc_i
    while acc < target and (l > 0 or r < bins - 1):
        wl = prof[l - 1] if l > 0 else -1
        wr = prof[r + 1] if r < bins - 1 else -1
        if wr >= wl:
            r += 1
            acc += max(wr, 0)
        else:
            l -= 1
            acc += max(wl, 0)

    # 简化版：只输出稀疏分布（每 3 档取 1，减小传输量）
    sparse = []
    for i in range(0, bins, 3):
        sparse.append({"p": round(centers[i], 3), "v": round(prof[i] / total, 6)})

    return {
        "poc": round(centers[poc_i], 3),
        "vah": round(centers[r], 3),
        "val": round(centers[l], 3),
        "poc_ratio": round(prof[poc_i] / total * 100, 2),
        "va_ratio": round((centers[r] - centers[l]) / centers[poc_i] * 100, 2) if centers[poc_i] else 0,
        "profile": sparse,
        "days": len(data),
    }


# ------------------------------------------------------------ 主计算

def analyze(bars, float_shares=0.0, bins=None, max_days=None, close_now=None):
    """
    bars: 升序 K线 [{day,open,high,low,close,volume}]
    float_shares: 流通股本（股），0 表示未知（自动退化）
    返回完整筹码结构 + 主力/散户分层 + 集中区
    """
    bins = bins or config.CHIP_BINS
    max_days = max_days or config.CHIP_MAX_DAYS
    if not bars or len(bars) < 20:
        return {"ok": False, "reason": "K线不足 20 根，无法计算筹码分布"}

    data = bars[-max_days:]
    price_now = close_now if close_now is not None else data[-1]["close"]

    lows = [b["low"] for b in data]
    highs = [b["high"] for b in data]
    lo = min(lows)
    hi = max(highs)
    if hi <= lo:
        hi = lo * 1.01
    pad = (hi - lo) * 0.02
    lo -= pad
    hi += pad
    step = (hi - lo) / bins
    centers = [lo + step * (i + 0.5) for i in range(bins)]

    # ---- 换手率基准
    vols = [b["volume"] for b in data]
    vol_ma20 = []
    s = 0.0
    for i, v in enumerate(vols):
        s += v
        if i >= 20:
            s -= vols[i - 20]
        vol_ma20.append(s / min(i + 1, 20))

    # ---- 价格分位（60日）
    pos60 = []
    for i in range(len(data)):
        w = data[max(0, i - 59):i + 1]
        l60 = min(x["low"] for x in w)
        h60 = max(x["high"] for x in w)
        pos60.append((data[i]["close"] - l60) / (h60 - l60) if h60 > l60 else 0.5)

    main = [0.0] * bins
    retail = [0.0] * bins
    k = config.CHIP_DECAY_K

    m_shares = []
    for i, b in enumerate(data):
        c = b["close"]
        o = b["open"]
        h = b["high"]
        l = b["low"]
        v = b["volume"]
        if v <= 0:
            m_shares.append(0.5)
            continue

        # 换手率
        if float_shares and float_shares > 0:
            turnover = v / float_shares
        else:
            # 退化：以 20 日均量为「1% 换手」的经验锚
            turnover = 0.01 * (v / vol_ma20[i]) if vol_ma20[i] > 0 else 0.01
        turnover = min(max(turnover, 0.0), 0.85)

        vr = v / vol_ma20[i] if vol_ma20[i] > 0 else 1.0
        r = (c - o) / o if o > 0 else 0.0
        p = pos60[i]

        # 主力参与度：低位 + 放量 + 上涨 → 主力吸筹；高位 + 放量 + 下跌 → 主力派发
        z = 0.9 * (vr - 1.0) + 5.0 * r + 1.8 * (0.5 - p)
        m = 0.5 + 0.42 * math.tanh(z)
        m = min(max(m, 0.05), 0.95)
        m_shares.append(m)

        avg = (h + l + c) / 3.0
        # 主力成交集中在均价附近（大单一次撮合），散户铺满整个区间（追价挂单）
        phi_m = _tri_weights(l, h, avg, centers, step, sharp=1.85)
        phi_s = _tri_weights(l, h, avg, centers, step, sharp=0.42)

        decay = min(0.92, turnover * k)
        dm = decay * m
        ds = decay * (1 - m)
        for j in range(bins):
            main[j] = main[j] * (1 - dm) + v * m * phi_m[j]
            retail[j] = retail[j] * (1 - ds) + v * (1 - m) * phi_s[j]

    total_main = sum(main)
    total_retail = sum(retail)
    total = total_main + total_retail
    if total <= 0:
        return {"ok": False, "reason": "筹码总量为 0"}

    # ---- 合并分布
    allw = [a + b for a, b in zip(main, retail)]

    # ---- 成本与获利盘
    main_cost = _weighted_mean(centers, main)
    retail_cost = _weighted_mean(centers, retail)
    all_cost = _weighted_mean(centers, allw)

    def profit_ratio(weights):
        below = sum(w for c, w in zip(centers, weights) if c <= price_now)
        t = sum(weights)
        return below / t if t > 0 else 0.0

    profit_all = profit_ratio(allw)
    profit_main = profit_ratio(main)
    profit_retail = profit_ratio(retail)

    p10 = _weighted_quantile(centers, allw, 0.10)
    p50 = _weighted_quantile(centers, allw, 0.50)
    p90 = _weighted_quantile(centers, allw, 0.90)
    concentration = (p90 - p10) / (p90 + p10) if (p90 + p10) else 1.0   # 越小越集中

    # ---- 集中区
    main_zone = _peak_zone(centers, main, config.CHIP_MAIN_PEAK_COVER)
    retail_zone = _peak_zone(centers, retail, config.CHIP_MAIN_PEAK_COVER)

    # ---- 套牢盘 / 获利盘（按金额占比）
    trapped = sum(w for c, w in zip(centers, allw) if c > price_now * 1.02) / total
    floating = sum(w for c, w in zip(centers, allw) if c < price_now * 0.98) / total

    # ---- 控盘度
    control = total_main / total if total else 0.0

    # ---- 筹码迁移：最近 10 日主力成本变化
    if len(data) >= 20:
        half = len(data) // 2
        prev_main = _weighted_mean(centers, main)   # 当前
        # 用「近 10 日主力参与度均值」判断吸筹/派发
        recent_m = sum(m_shares[-10:]) / 10.0
        older_m = sum(m_shares[-40:-10]) / 30.0 if len(m_shares) >= 40 else recent_m
        flow = (recent_m - older_m) / max(older_m, 1e-9)
    else:
        flow = 0.0

    # ---- 与现价的距离
    dev_main = (price_now - main_cost) / main_cost * 100 if main_cost else 0.0
    dev_retail = (price_now - retail_cost) / retail_cost * 100 if retail_cost else 0.0

    # ---- 逐档输出（前端画横向直方图用）
    dist = []
    for i in range(bins):
        dist.append({
            "p": round(centers[i], 3),
            "m": round(main[i] / max(total_main, 1e-9), 6),
            "r": round(retail[i] / max(total_retail, 1e-9), 6),
            "t": round(allw[i] / total, 6),
        })

    return {
        "ok": True,
        "price": round(price_now, 3),
        "bins": bins,
        "range": [round(lo, 3), round(hi, 3)],
        "distribution": dist,
        "peaks": _find_peaks(centers, allw, 3),
        "main_peaks": _find_peaks(centers, main, 3),
        "retail_peaks": _find_peaks(centers, retail, 3),
        "main_cost": round(main_cost, 3),
        "retail_cost": round(retail_cost, 3),
        "avg_cost": round(all_cost, 3),
        "profit_ratio": round(profit_all * 100, 2),
        "profit_main": round(profit_main * 100, 2),
        "profit_retail": round(profit_retail * 100, 2),
        "p10": round(p10, 3), "p50": round(p50, 3), "p90": round(p90, 3),
        "concentration": round(concentration, 4),
        "main_zone": None if not main_zone else {
            "low": round(main_zone[0], 3), "high": round(main_zone[1], 3),
            "peak": round(main_zone[2], 3),
            "width_pct": round((main_zone[1] - main_zone[0]) / main_zone[2] * 100, 2) if main_zone[2] else 0,
        },
        "retail_zone": None if not retail_zone else {
            "low": round(retail_zone[0], 3), "high": round(retail_zone[1], 3),
            "peak": round(retail_zone[2], 3),
            "width_pct": round((retail_zone[1] - retail_zone[0]) / retail_zone[2] * 100, 2) if retail_zone[2] else 0,
        },
        "separation": round((retail_cost - main_cost) / main_cost * 100, 2) if main_cost else 0.0,
        "trapped_ratio": round(trapped * 100, 2),
        "floating_ratio": round(floating * 100, 2),
        "control": round(control * 100, 2),
        "flow": round(flow * 100, 2),
        "dev_main": round(dev_main, 2),
        "dev_retail": round(dev_retail, 2),
        "float_shares": float_shares,
        "main_mass": round(total_main, 2),
        "retail_mass": round(total_retail, 2),
        "days_used": len(data),
    }
