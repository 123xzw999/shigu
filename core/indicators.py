# -*- coding: utf-8 -*-
"""
技术指标内核 · indicators.py
============================
零依赖纯 Python 实现。命名与参数约定对齐两个开源项目：

  * **pandas-ta** (v0.3.14b0) —— 函数名与默认参数（sma/ema/rsi/macd/bbands/
    stoch/atr/adx/obv/cci/willr/roc/mfi/donchian/keltner/supertrend/trix/ao/cmf）
  * **srl-python-indicators** —— 指标分组方式（Trend / Momentum / Volatility /
    Volume / Others），以及「多指标共振」的组合思路

所有函数签名统一为 f(series, period, ...) -> list（与输入等长，预热期为 None）。
这样做的好处：调用方不需要关心索引对齐，直接按 bar 下标取值即可。
"""

import math

from . import config

__all__ = [
    "sma", "ema", "wma", "rma", "dema", "tema", "rolling_std", "rolling_max",
    "rolling_min", "slope", "linreg", "corr",
    "rsi", "stoch", "kdj", "willr", "cci", "mfi", "roc", "trix", "ao", "uo",
    "macd", "adx", "supertrend", "aroon", "donchian", "keltner",
    "bbands", "atr", "natr", "hv",
    "obv", "ad", "cmf", "vwap", "vol_ratio", "eom",
]

NAN = None


# ============================================================ 工具

def _n(x):
    return x if x is not None else float("nan")


def _clean(vals):
    """把 nan 转成 None，方便 JSON 序列化。"""
    return [None if (v is None or v != v) else round(v, 6) for v in vals]


def _sma_raw(vals, n):
    """简单均线。自动跳过前导 nan（这一点很关键：MACD/KDJ 的二次平滑会喂进 nan）。"""
    out = [float("nan")] * len(vals)
    if n <= 0:
        return out
    buf = []
    for i, v in enumerate(vals):
        if v is None or v != v:
            continue
        buf.append(v)
        if len(buf) > n:
            buf.pop(0)
        if len(buf) == n:
            out[i] = sum(buf) / n
    return out


def _ema_raw(vals, n):
    out = [float("nan")] * len(vals)
    if not vals or n <= 0:
        return out
    k = 2.0 / (n + 1.0)
    prev = None
    buf = []
    for i, v in enumerate(vals):
        if v is None or v != v:
            continue
        if prev is None:
            buf.append(v)
            if len(buf) >= n:
                prev = sum(buf) / len(buf)
                out[i] = prev
            continue
        prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def _rma_raw(vals, n):
    """Wilder 平滑（RSI/ATR/ADX 用），同样跳过前导 nan。"""
    out = [float("nan")] * len(vals)
    if not vals or n <= 0:
        return out
    prev = None
    buf = []
    for i, v in enumerate(vals):
        if v is None or v != v:
            continue
        if prev is None:
            buf.append(v)
            if len(buf) >= n:
                prev = sum(buf) / len(buf)
                out[i] = prev
            continue
        prev = (prev * (n - 1) + v) / n
        out[i] = prev
    return out


# ============================================================ 均线族

def sma(values, period=20):
    return _clean(_sma_raw([_n(v) for v in values], period))


def ema(values, period=20):
    return _clean(_ema_raw([_n(v) for v in values], period))


def wma(values, period=20):
    n = len(values)
    out = [float("nan")] * n
    denom = period * (period + 1) / 2.0
    for i in range(period - 1, n):
        acc = 0.0
        for j in range(period):
            acc += _n(values[i - period + 1 + j]) * (j + 1)
        out[i] = acc / denom
    return _clean(out)


def rma(values, period=14):
    return _clean(_rma_raw([_n(v) for v in values], period))


def dema(values, period=20):
    e1 = _ema_raw([_n(v) for v in values], period)
    e2 = _ema_raw(e1, period)
    return _clean([2 * a - b if a == a and b == b else float("nan") for a, b in zip(e1, e2)])


def tema(values, period=20):
    e1 = _ema_raw([_n(v) for v in values], period)
    e2 = _ema_raw(e1, period)
    e3 = _ema_raw(e2, period)
    return _clean([3 * a - 3 * b + c if a == a and b == b and c == c else float("nan")
                   for a, b, c in zip(e1, e2, e3)])


def rolling_std(values, period=20):
    n = len(values)
    out = [float("nan")] * n
    for i in range(period - 1, n):
        seg = [_n(v) for v in values[i - period + 1:i + 1]]
        m = sum(seg) / period
        out[i] = math.sqrt(sum((x - m) ** 2 for x in seg) / period)
    return _clean(out)


def rolling_max(values, period=20):
    n = len(values)
    out = [float("nan")] * n
    for i in range(period - 1, n):
        out[i] = max(_n(v) for v in values[i - period + 1:i + 1])
    return _clean(out)


def rolling_min(values, period=20):
    n = len(values)
    out = [float("nan")] * n
    for i in range(period - 1, n):
        out[i] = min(_n(v) for v in values[i - period + 1:i + 1])
    return _clean(out)


def linreg(values, period=20):
    """返回 (斜率, 截距, R²)，对最后 period 个点做最小二乘。"""
    seg = [_n(v) for v in values[-period:]] if len(values) >= period else [_n(v) for v in values]
    m = len(seg)
    if m < 2:
        return 0.0, seg[-1] if seg else 0.0, 0.0
    xs = list(range(m))
    mx = sum(xs) / m
    my = sum(seg) / m
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, seg))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in seg)
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    r2 = (sxy ** 2) / (sxx * syy) if sxx and syy else 0.0
    return slope, intercept, r2


def slope(values, period=20):
    """归一化斜率：每根K线的相对变化率（%）。"""
    seg = [_n(v) for v in values[-period:]]
    if len(seg) < 3:
        return 0.0
    s, _, _ = linreg(seg, len(seg))
    base = sum(seg) / len(seg)
    return (s / base * 100) if base else 0.0


def corr(a, b, period=20):
    a = [_n(x) for x in a[-period:]]
    b = [_n(x) for x in b[-period:]]
    m = min(len(a), len(b))
    if m < 3:
        return 0.0
    a, b = a[-m:], b[-m:]
    ma, mb = sum(a) / m, sum(b) / m
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(va * vb)


# ============================================================ 动量族

def rsi(close, period=14):
    n = len(close)
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = close[i] - close[i - 1]
        gains[i] = max(d, 0.0)
        losses[i] = max(-d, 0.0)
    ag = _rma_raw(gains, period)
    al = _rma_raw(losses, period)
    out = [float("nan")] * n
    for i in range(n):
        if ag[i] == ag[i] and al[i] == al[i]:
            out[i] = 100.0 if al[i] == 0 else 100.0 - 100.0 / (1 + ag[i] / al[i])
    return _clean(out)


def stoch(high, low, close, k=14, d=3, smooth=3):
    """返回 (K, D)，与 pandas-ta stoch 一致（0~100）"""
    n = len(close)
    raw = [float("nan")] * n
    for i in range(k - 1, n):
        hh = max(high[i - k + 1:i + 1])
        ll = min(low[i - k + 1:i + 1])
        raw[i] = 100.0 * (close[i] - ll) / (hh - ll) if hh > ll else 50.0
    kk = _sma_raw([_n(v) for v in raw], smooth)
    dd = _sma_raw(kk, d)
    return _clean(kk), _clean(dd)


def kdj(high, low, close, n=9, m1=3, m2=3):
    """国内常用 KDJ（K/D 用 SMA 递推，J = 3K - 2D）"""
    ln = len(close)
    rsv = [float("nan")] * ln
    for i in range(n - 1, ln):
        hh = max(high[i - n + 1:i + 1])
        ll = min(low[i - n + 1:i + 1])
        rsv[i] = 100.0 * (close[i] - ll) / (hh - ll) if hh > ll else 50.0
    kk = [float("nan")] * ln
    dd = [float("nan")] * ln
    pk = pd = 50.0
    for i in range(ln):
        if rsv[i] != rsv[i]:
            continue
        pk = (m1 - 1) / m1 * pk + 1.0 / m1 * rsv[i]
        pd = (m2 - 1) / m2 * pd + 1.0 / m2 * pk
        kk[i], dd[i] = pk, pd
    jj = [3 * a - 2 * b if a == a and b == b else float("nan") for a, b in zip(kk, dd)]
    return _clean(kk), _clean(dd), _clean(jj)


def willr(high, low, close, period=14):
    n = len(close)
    out = [float("nan")] * n
    for i in range(period - 1, n):
        hh = max(high[i - period + 1:i + 1])
        ll = min(low[i - period + 1:i + 1])
        out[i] = -100.0 * (hh - close[i]) / (hh - ll) if hh > ll else -50.0
    return _clean(out)


def cci(high, low, close, period=20):
    n = len(close)
    tp = [(h + l + c) / 3.0 for h, l, c in zip(high, low, close)]
    ma = _sma_raw(tp, period)
    out = [float("nan")] * n
    for i in range(period - 1, n):
        seg = tp[i - period + 1:i + 1]
        md = sum(abs(x - ma[i]) for x in seg) / period
        out[i] = (tp[i] - ma[i]) / (0.015 * md) if md > 0 else 0.0
    return _clean(out)


def mfi(high, low, close, volume, period=14):
    n = len(close)
    tp = [(h + l + c) / 3.0 for h, l, c in zip(high, low, close)]
    pos = [0.0] * n
    neg = [0.0] * n
    for i in range(1, n):
        mf = tp[i] * volume[i]
        if tp[i] > tp[i - 1]:
            pos[i] = mf
        elif tp[i] < tp[i - 1]:
            neg[i] = mf
    out = [float("nan")] * n
    for i in range(period, n):
        p = sum(pos[i - period + 1:i + 1])
        q = sum(neg[i - period + 1:i + 1])
        out[i] = 100.0 if q == 0 else 100.0 - 100.0 / (1 + p / q)
    return _clean(out)


def roc(close, period=12):
    n = len(close)
    out = [float("nan")] * n
    for i in range(period, n):
        base = close[i - period]
        out[i] = (close[i] - base) / base * 100 if base else 0.0
    return _clean(out)


def trix(close, period=15):
    e = _ema_raw([_n(v) for v in close], period)
    e = _ema_raw(e, period)
    e = _ema_raw(e, period)
    n = len(e)
    out = [float("nan")] * n
    for i in range(1, n):
        if e[i] == e[i] and e[i - 1] == e[i - 1] and e[i - 1]:
            out[i] = (e[i] - e[i - 1]) / e[i - 1] * 100
    return _clean(out)


def ao(high, low, fast=5, slow=34):
    med = [(h + l) / 2 for h, l in zip(high, low)]
    a = _sma_raw(med, fast)
    b = _sma_raw(med, slow)
    return _clean([x - y if x == x and y == y else float("nan") for x, y in zip(a, b)])


def uo(high, low, close, p1=7, p2=14, p3=28):
    n = len(close)
    bp = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        bp[i] = close[i] - min(low[i], close[i - 1])
        tr[i] = max(high[i], close[i - 1]) - min(low[i], close[i - 1])
    out = [float("nan")] * n
    for i in range(p3, n):
        def avg(p):
            s1 = sum(bp[i - p + 1:i + 1]); s2 = sum(tr[i - p + 1:i + 1])
            return s1 / s2 if s2 else 0.0
        a1, a2, a3 = avg(p1), avg(p2), avg(p3)
        out[i] = 100.0 * (4 * a1 + 2 * a2 + a3) / 7.0
    return _clean(out)


# ============================================================ 趋势族

def macd(close, fast=12, slow=26, signal=9):
    """返回 (dif, dea, hist)，hist 采用 (dif-dea)*2 的国内习惯。"""
    ef = _ema_raw([_n(v) for v in close], fast)
    es = _ema_raw([_n(v) for v in close], slow)
    dif = [a - b if a == a and b == b else float("nan") for a, b in zip(ef, es)]
    dea = _ema_raw(dif, signal)
    hist = [(a - b) * 2 if a == a and b == b else float("nan") for a, b in zip(dif, dea)]
    return _clean(dif), _clean(dea), _clean(hist)


def adx(high, low, close, period=14):
    """返回 (adx, plus_di, minus_di)"""
    n = len(close)
    tr = [0.0] * n
    pdm = [0.0] * n
    ndm = [0.0] * n
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
    atr_ = _rma_raw(tr, period)
    sp = _rma_raw(pdm, period)
    sn = _rma_raw(ndm, period)
    pdi = [100 * a / b if b and a == a and b == b else float("nan") for a, b in zip(sp, atr_)]
    ndi = [100 * a / b if b and a == a and b == b else float("nan") for a, b in zip(sn, atr_)]
    dx = [100 * abs(a - b) / (a + b) if a == a and b == b and (a + b) else float("nan")
          for a, b in zip(pdi, ndi)]
    ax = _rma_raw(dx, period)
    return _clean(ax), _clean(pdi), _clean(ndi)


def supertrend(high, low, close, period=10, mult=3.0):
    """返回 (st_line, direction) direction: 1 多头 / -1 空头"""
    n = len(close)
    atr_ = _rma_raw([0.0] + [max(high[i] - low[i], abs(high[i] - close[i - 1]),
                                  abs(low[i] - close[i - 1])) for i in range(1, n)], period)
    st = [float("nan")] * n
    dirs = [0] * n
    fu = fl = None
    for i in range(n):
        if atr_[i] != atr_[i]:
            continue
        hl2 = (high[i] + low[i]) / 2
        ub = hl2 + mult * atr_[i]
        lb = hl2 - mult * atr_[i]
        if fu is None:
            fu, fl = ub, lb
            st[i], dirs[i] = lb, 1
            continue
        if close[i - 1] > fu:
            fu = ub
        else:
            fu = min(ub, fu)
        if close[i - 1] < fl:
            fl = lb
        else:
            fl = max(lb, fl)
        if close[i] > fu:
            dirs[i] = 1
            st[i] = fl
        elif close[i] < fl:
            dirs[i] = -1
            st[i] = fu
        else:
            dirs[i] = dirs[i - 1] if dirs[i - 1] else 1
            st[i] = fl if dirs[i] == 1 else fu
    return _clean(st), dirs


def aroon(high, low, period=25):
    n = len(high)
    up = [float("nan")] * n
    dn = [float("nan")] * n
    for i in range(period, n):
        seg_h = high[i - period:i + 1]
        seg_l = low[i - period:i + 1]
        up[i] = 100.0 * seg_h.index(max(seg_h)) / period
        dn[i] = 100.0 * seg_l.index(min(seg_l)) / period
    return _clean(up), _clean(dn)


def donchian(high, low, period=20):
    return rolling_max(high, period), rolling_min(low, period)


def keltner(high, low, close, period=20, mult=2.0):
    mid = _ema_raw([_n(v) for v in close], period)
    atr_ = _rma_raw([0.0] + [max(high[i] - low[i], abs(high[i] - close[i - 1]),
                                  abs(low[i] - close[i - 1])) for i in range(1, len(close))], period)
    up = [m + mult * a if m == m and a == a else float("nan") for m, a in zip(mid, atr_)]
    lo = [m - mult * a if m == m and a == a else float("nan") for m, a in zip(mid, atr_)]
    return _clean(up), _clean(mid), _clean(lo)


# ============================================================ 波动族

def bbands(close, period=20, k=2.0):
    mid = _sma_raw([_n(v) for v in close], period)
    sd = [float("nan")] * len(close)
    for i in range(period - 1, len(close)):
        seg = close[i - period + 1:i + 1]
        m = mid[i]
        sd[i] = math.sqrt(sum((x - m) ** 2 for x in seg) / period)
    up = [m + k * s if m == m and s == s else float("nan") for m, s in zip(mid, sd)]
    lo = [m - k * s if m == m and s == s else float("nan") for m, s in zip(mid, sd)]
    width = [(u - l) / m * 100 if m and u == u and l == l else float("nan")
             for u, l, m in zip(up, lo, mid)]
    return _clean(up), _clean(mid), _clean(lo), _clean(width)


def atr(high, low, close, period=14):
    n = len(close)
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    return _clean(_rma_raw(tr, period))


def natr(high, low, close, period=14):
    a = atr(high, low, close, period)
    return _clean([(x / c * 100) if x is not None and c else float("nan")
                   for x, c in zip(a, close)])


def hv(close, period=20):
    """年化历史波动率（%）"""
    n = len(close)
    rets = [0.0] * n
    for i in range(1, n):
        rets[i] = math.log(close[i] / close[i - 1]) if close[i - 1] > 0 and close[i] > 0 else 0.0
    out = [float("nan")] * n
    for i in range(period, n):
        seg = rets[i - period + 1:i + 1]
        m = sum(seg) / period
        sd = math.sqrt(sum((x - m) ** 2 for x in seg) / period)
        out[i] = sd * math.sqrt(244) * 100
    return _clean(out)


# ============================================================ 量能族

def obv(close, volume):
    n = len(close)
    out = [0.0] * n
    acc = 0.0
    for i in range(1, n):
        if close[i] > close[i - 1]:
            acc += volume[i]
        elif close[i] < close[i - 1]:
            acc -= volume[i]
        out[i] = acc
    return _clean(out)


def ad(high, low, close, volume):
    n = len(close)
    out = [0.0] * n
    acc = 0.0
    for i in range(n):
        rng = high[i] - low[i]
        mfm = ((close[i] - low[i]) - (high[i] - close[i])) / rng if rng else 0.0
        acc += mfm * volume[i]
        out[i] = acc
    return _clean(out)


def cmf(high, low, close, volume, period=20):
    n = len(close)
    mfv = [0.0] * n
    for i in range(n):
        rng = high[i] - low[i]
        mfm = ((close[i] - low[i]) - (high[i] - close[i])) / rng if rng else 0.0
        mfv[i] = mfm * volume[i]
    out = [float("nan")] * n
    for i in range(period - 1, n):
        vs = sum(volume[i - period + 1:i + 1])
        out[i] = sum(mfv[i - period + 1:i + 1]) / vs if vs else 0.0
    return _clean(out)


def vwap(high, low, close, volume, period=20):
    n = len(close)
    tp = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
    out = [float("nan")] * n
    for i in range(period - 1, n):
        vs = sum(volume[i - period + 1:i + 1])
        out[i] = sum(t * v for t, v in zip(tp[i - period + 1:i + 1],
                                           volume[i - period + 1:i + 1])) / vs if vs else tp[i]
    return _clean(out)


def vol_ratio(volume, period=5):
    """量比：当日量 / 前 period 日均量"""
    n = len(volume)
    ma = _sma_raw([_n(v) for v in volume], period)
    out = [float("nan")] * n
    for i in range(1, n):
        base = ma[i - 1]
        if base == base and base > 0:
            out[i] = volume[i] / base
    return _clean(out)


def eom(high, low, volume, period=14):
    """Ease of Movement"""
    n = len(high)
    dm = [0.0] * n
    for i in range(1, n):
        mid_move = ((high[i] + low[i]) - (high[i - 1] + low[i - 1])) / 2
        br = volume[i] / 1e8 / max(high[i] - low[i], 1e-9) if volume[i] else 0.0
        dm[i] = mid_move / br if br else 0.0
    return _clean(_sma_raw(dm, period))


# ============================================================ 汇总

def compute_all(bars, float_shares=0.0):
    """
    一次性算完整套指标，返回 dict（每个 key 都是等长 list）。
    bars: [{day,open,high,low,close,volume}]
    """
    if not bars:
        return {}
    close = [b["close"] for b in bars]
    high = [b["high"] for b in bars]
    low = [b["low"] for b in bars]
    open_ = [b["open"] for b in bars]
    vol = [b["volume"] for b in bars]

    res = {}
    for p in config.MA_PERIODS:
        res["ma%d" % p] = sma(close, p)
    res["ema12"] = ema(close, 12)
    res["ema26"] = ema(close, 26)

    res["dif"], res["dea"], res["macd"] = macd(close, config.MACD_FAST,
                                               config.MACD_SLOW, config.MACD_SIGNAL)
    res["rsi6"] = rsi(close, 6)
    res["rsi14"] = rsi(close, config.RSI_PERIOD)
    res["k"], res["d"], res["j"] = kdj(high, low, close, config.KDJ_N,
                                       config.KDJ_M1, config.KDJ_M2)
    res["boll_up"], res["boll_mid"], res["boll_low"], res["boll_w"] = bbands(
        close, config.BOLL_N, config.BOLL_K)
    res["atr"] = atr(high, low, close, config.ATR_PERIOD)
    res["natr"] = natr(high, low, close, config.ATR_PERIOD)
    res["adx"], res["pdi"], res["ndi"] = adx(high, low, close, config.ADX_PERIOD)
    res["cci"] = cci(high, low, close, config.CCI_PERIOD)
    res["wr"] = willr(high, low, close, config.WR_PERIOD)
    res["mfi"] = mfi(high, low, close, vol, config.MFI_PERIOD)
    res["roc"] = roc(close, 12)
    res["obv"] = obv(close, vol)
    res["obv_ma"] = sma([_n(v) for v in res["obv"]], config.OBV_MA)
    res["cmf"] = cmf(high, low, close, vol, 20)
    res["vwap"] = vwap(high, low, close, vol, 20)
    res["vr"] = vol_ratio(vol, 5)
    res["hv"] = hv(close, 20)
    res["st"], res["st_dir"] = supertrend(high, low, close, 10, 3.0)
    res["dc_up"], res["dc_low"] = donchian(high, low, 20)
    res["up"], res["mid"], res["low"] = keltner(high, low, close, 20, 2.0)
    res["ao"] = ao(high, low, 5, 34)
    res["trix"] = trix(close, 15)
    res["eom"] = eom(high, low, vol, 14)

    # 换手率
    if float_shares and float_shares > 0:
        res["turnover"] = _clean([v / float_shares * 100 for v in vol])
    else:
        res["turnover"] = [None] * len(bars)

    res["_close"] = close
    res["_high"] = high
    res["_low"] = low
    res["_open"] = open_
    res["_vol"] = vol
    return res
