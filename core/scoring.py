# -*- coding: utf-8 -*-
"""
自研评分函数 · scoring.py
=========================
**TRS · Trend Resonance Score（趋势共振评分）**

这不是把指标简单相加，而是一个带软饱和的多维共振函数：

    D_i ∈ [-1, 1]   第 i 个维度的标准化得分（tanh 软饱和，避免极端值主导）
    w_i             维度权重（config.SCORE_WEIGHTS）
    S   = 100 · tanh( κ · Σ w_i D_i / Σ w_i )        κ = 2.2
    A   = |Σ w_i D_i| / Σ w_i |D_i|                   共振一致性 ∈ [0,1]
    Conf= A · (1 - e^(-n/80)) · (0.55 + 0.45·g)       置信度，g 为趋势清晰度

为什么用 tanh：原始指标是无界的（RSI 可以到 90，MACD 柱可以很大），
直接线性加权会让某个维度在极端行情下吞掉其他所有维度。
tanh 把每个维度压到 [-1,1]，且在小值区近似线性、大值区饱和，
等价于「温和的软阈值」——这是本系统与简单打分卡最本质的区别。

七个维度
--------
T 趋势：均线结构 + 回归斜率 + ADX 方向
M 动量：RSI + MACD 柱 + ROC + KDJ
V 量能：量比 + OBV 斜率 + CMF + 量价相关
C 筹码：控盘度 + 成本偏离 + 集中度 + 获利盘 + 吸筹速度
L 缠论：买卖点 + 背驰 + 中枢位置 + 走势类型
P 形态：K线形态加权
R 风险：波动率 + 回撤 + 乖离（负向）
"""

import math

from . import config
from . import indicators as ta

KAPPA = 2.2


def _th(x):
    return math.tanh(max(-8.0, min(8.0, x)))


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _last(series, default=0.0):
    if not series:
        return default
    v = series[-1]
    return default if v is None else v


def _lastv(series, back=0, default=None):
    if not series or len(series) <= back:
        return default
    v = series[-1 - back]
    return default if v is None else v


# ============================================================ 各维度

def dim_trend(bars, ind):
    close = ind["_close"]
    price = close[-1]
    ma5, ma20, ma60 = _last(ind["ma5"]), _last(ind["ma20"]), _last(ind["ma60"])
    x1 = (ma5 / ma20 - 1) * 100 if ma20 else 0.0
    x2 = (ma20 / ma60 - 1) * 100 if ma60 else 0.0
    beta = ta.slope([math.log(max(c, 1e-9)) for c in close[-25:]], 20) * 1.0
    pdi = _last(ind["pdi"], 20.0)
    ndi = _last(ind["ndi"], 20.0)
    adx = _last(ind["adx"], 20.0)
    x4 = (pdi - ndi) / 25.0

    core = _th(0.32 * x1 + 0.22 * x2 + 3.2 * beta + 0.22 * x4)
    clarity = min(1.0, 0.35 + 0.65 * min(adx / 30.0, 1.0))
    s = core * clarity

    ev = []
    if x1 > 0.5:
        ev.append("MA5 上穿 MA20 之上 %.2f%%" % x1)
    elif x1 < -0.5:
        ev.append("MA5 位于 MA20 之下 %.2f%%" % x1)
    if x2 > 0.5:
        ev.append("中期均线多头（MA20 > MA60 %.2f%%）" % x2)
    elif x2 < -0.5:
        ev.append("中期均线空头（MA20 < MA60 %.2f%%）" % x2)
    ev.append("20日回归斜率 %+.3f%%/日" % beta)
    ev.append("ADX %.1f（%s）" % (adx, "趋势明确" if adx > 25 else "趋势偏弱" if adx < 20 else "趋势形成中"))
    ev.append("DI 差 %+.1f" % (pdi - ndi))
    return _clamp(s), ev


def dim_momentum(bars, ind):
    rsi = _last(ind["rsi14"], 50.0)
    hist = _last(ind["macd"])
    dif = _last(ind["dif"])
    dea = _last(ind["dea"])
    atr = _last(ind["atr"], 1.0) or 1.0
    roc = _last(ind["roc"])
    j = _last(ind["j"], 50.0)
    close = ind["_close"]

    m1 = (rsi - 50) / 20.0
    m2 = hist / (atr * 0.9) if atr else 0.0
    m3 = roc / 12.0
    m4 = (j - 50) / 45.0
    s = _th(0.45 * m1 + 0.50 * m2 + 0.32 * m3 + 0.20 * m4)

    ev = ["RSI14 = %.1f（%s）" % (rsi, "超买" if rsi > 70 else "超卖" if rsi < 30 else "中性")]
    ev.append("MACD 柱 %.4f，DIF %.4f / DEA %.4f（%s）" %
              (hist, dif, dea, "金叉区" if dif > dea else "死叉区"))
    ev.append("ROC12 = %+.2f%%" % roc)
    ev.append("KDJ J = %.1f" % j)
    if len(close) > 6:
        ev.append("近5日涨跌 %+.2f%%" % ((close[-1] / close[-6] - 1) * 100))
    return _clamp(s), ev


def dim_volume(bars, ind):
    vol = ind["_vol"]
    close = ind["_close"]
    vr = _last(ind["vr"], 1.0)
    obv = ind["obv"]
    obv_slope = 0.0
    if len(obv) >= 21 and obv[-21] is not None and obv[-1] is not None:
        base = abs(obv[-21]) or 1.0
        obv_slope = (obv[-1] - obv[-21]) / base
    cmf = _last(ind["cmf"])
    dc = [close[i] - close[i - 1] for i in range(1, len(close))]
    vv = vol[1:]
    corr = ta.corr(dc, vv, 20) if len(dc) >= 20 else 0.0

    v1 = (vr - 1) * 0.75
    v2 = obv_slope * 9.0
    v3 = cmf * 3.2
    v4 = corr * 0.55
    s = _th(0.40 * v1 + 0.45 * v2 + 0.40 * v3 + 0.32 * v4)

    ev = ["量比 %.2f（%s）" % (vr, "放量" if vr > 1.3 else "缩量" if vr < 0.8 else "平量")]
    ev.append("OBV 20日变化 %+.2f%%" % (obv_slope * 100))
    ev.append("CMF20 = %+.3f（%s）" % (cmf, "资金净流入" if cmf > 0.05 else "资金净流出" if cmf < -0.05 else "资金平衡"))
    ev.append("量价相关 %.2f（%s）" % (corr, "量价齐升" if corr > 0.2 else "量价背离" if corr < -0.2 else "关系中性"))
    return _clamp(s), ev


def dim_chip(chip):
    if not chip or not chip.get("ok"):
        return 0.0, ["筹码数据不可用"]
    ctrl = chip["control"] / 100.0
    dev = chip["dev_main"] / 100.0
    conc = chip["concentration"]
    profit = chip["profit_ratio"] / 100.0
    flow = chip["flow"] / 100.0

    c1 = _clamp((ctrl - 0.5) * 2.0)
    c2 = _clamp(-dev * 3.2)
    c3 = _clamp((0.30 - conc) / 0.22)
    c4 = _clamp(1.4 - abs(profit - 0.55) * 3.0)
    c5 = _clamp(flow * 4.0)
    s = _th(0.50 * c1 + 0.55 * c2 + 0.30 * c3 + 0.38 * c4 + 0.34 * c5)

    ev = ["主力控盘度 %.1f%%（%s）" % (chip["control"],
                                    "高度控盘" if chip["control"] > 60 else "中度控盘" if chip["control"] > 45 else "散户主导")]
    ev.append("现价相对主力成本 %+.2f%%" % chip["dev_main"])
    ev.append("90%%成本区间 %.2f ~ %.2f，集中度 %.3f（%s）" %
              (chip["p10"], chip["p90"], chip["concentration"],
               "高度集中" if chip["concentration"] < 0.18 else "较分散" if chip["concentration"] > 0.32 else "中等"))
    ev.append("获利盘 %.1f%%，上方套牢 %.1f%%" % (chip["profit_ratio"], chip["trapped_ratio"]))
    ev.append("近10日主力筹码%s %.1f%%" % ("流入" if chip["flow"] > 0 else "流出", abs(chip["flow"])))
    return _clamp(s), ev


def dim_chan(chan):
    if not chan or not chan.get("ok"):
        return 0.0, ["缠论数据不可用"]
    l1 = l2 = l3 = l4 = 0.0
    ev = []

    sig = chan.get("last_signal")
    if sig:
        age = chan["bars_len"] - 1 - sig["bar"] if "bars_len" in chan else 0
        decay = max(0.25, 1.0 - age / 90.0)
        l1 = sig["strength"] * decay * (1 if sig["side"] == "buy" else -1)
        ev.append("最近买卖点：%s（%s，强度 %.2f）" % (sig["type"], sig["day"], sig["strength"]))

    divs = chan.get("divergences") or []
    if divs:
        d = divs[-1]
        l2 = 0.6 if d["kind"] == "底背驰" else -0.6
        ev.append("最近背驰：%s（面积萎缩 %.2f 倍）" % (d["kind"], d["shrink"]))
    else:
        ev.append("近期无明显背驰")

    pos = chan.get("position")
    l3 = {"中枢上方": 0.35, "中枢内部": 0.0, "中枢下方": -0.35}.get(pos, 0.0)
    if chan.get("cur_zs"):
        z = chan["cur_zs"]
        ev.append("当前中枢 [%.2f, %.2f]，价格处于%s" % (z["zd"], z["zg"], pos))

    tr = chan.get("trend")
    l4 = {"上涨趋势": 0.32, "震荡上行": 0.16, "盘整": 0.0,
          "震荡下行": -0.16, "下跌趋势": -0.32}.get(tr, 0.0)
    ev.append("走势类型：%s" % tr)

    s = _th(1.20 * l1 + 0.90 * l2 + 1.00 * l3 + 1.00 * l4)
    ev.append("笔 %d / 线段 %d / 中枢 %d" % (chan.get("bi_count", 0),
                                          chan.get("duan_count", 0), chan.get("zs_count", 0)))
    return _clamp(s), ev


def dim_pattern(pat_sum):
    s = _th(pat_sum.get("score", 0.0) * 1.15)
    ev = [pat_sum.get("text", "")]
    if pat_sum.get("bull") or pat_sum.get("bear"):
        ev.append("近8根K线：看涨形态 %d 个 / 看跌形态 %d 个" % (pat_sum["bull"], pat_sum["bear"]))
    return _clamp(s), ev


def dim_risk(bars, ind, period_days=1.0):
    """
    风险维度。period_days 用来把不同周期的波动率拉到同一把尺子上 ——
    同一只股票周线的 NATR 天然是日线的 √5 倍，不做归一化的话
    换个周期就从「低风险」变成「高风险」，那这个维度就失去意义了。
    """
    k = math.sqrt(max(period_days, 0.01))
    natr = _last(ind["natr"], 2.0) / k
    close = ind["_close"]
    ma20 = _last(ind["ma20"], close[-1])
    bias = (close[-1] / ma20 - 1) * 100 if ma20 else 0.0
    w = close[-60:] if len(close) >= 60 else close
    peak = -1e9
    mdd = 0.0
    for c in w:
        peak = max(peak, c)
        mdd = max(mdd, (peak - c) / peak if peak else 0)
    hv = _last(ind["hv"], 25.0) / k

    r1 = (natr - 2.6) / 2.6
    r2 = (mdd - 0.12) / 0.15
    r3 = (abs(bias) - 6.0) / 10.0
    r4 = (hv - 30.0) / 25.0
    s = -_th(0.55 * r1 + 0.60 * r2 + 0.45 * r3 + 0.30 * r4)

    ev = ["ATR 占价 %.2f%%（波动%s）" % (natr, "偏高" if natr > 4 else "温和" if natr < 2.5 else "中等")]
    ev.append("60日最大回撤 %.2f%%" % (mdd * 100))
    ev.append("20日乖离率 %+.2f%%" % bias)
    ev.append("年化波动率 %.1f%%" % hv)
    return _clamp(s), ev


# ============================================================ 汇总

LEVELS = [
    (62, "强烈看多", "strong_bull", "#e01b1b"),
    (40, "看多", "bull", "#ef4b4b"),
    (14, "偏多", "weak_bull", "#f08a8a"),
    (-14, "中性", "neutral", "#8a8a8a"),
    (-40, "偏空", "weak_bear", "#6fb8a0"),
    (-62, "看空", "bear", "#1ba784"),
    (-101, "强烈看空", "strong_bear", "#0d8a6a"),
]


def _level(score):
    for th, name, key, color in LEVELS:
        if score >= th:
            return {"name": name, "key": key, "color": color}
    return {"name": "强烈看空", "key": "strong_bear", "color": "#0d8a6a"}


def _dim_tag(v):
    if v > 0.45:
        return "强多"
    if v > 0.15:
        return "偏多"
    if v >= -0.15:
        return "中性"
    if v > -0.45:
        return "偏空"
    return "强空"


def compute(bars, ind, chip, chan, pat_sum, phase_info, period_days=1.0):
    """返回完整评分结果。period_days：每根K线代表多少个交易日（日=1，周=5，月=21）"""
    dims = []
    ts, tev = dim_trend(bars, ind)
    dims.append(("trend", "趋势", ts, tev))
    ms, mev = dim_momentum(bars, ind)
    dims.append(("momentum", "动量", ms, mev))
    vs, vev = dim_volume(bars, ind)
    dims.append(("volume", "量能", vs, vev))
    cs, cev = dim_chip(chip)
    dims.append(("chip", "筹码", cs, cev))
    ls, lev = dim_chan(chan)
    dims.append(("chan", "缠论", ls, lev))
    ps, pev = dim_pattern(pat_sum)
    dims.append(("pattern", "形态", ps, pev))
    rs, rev = dim_risk(bars, ind, period_days)
    dims.append(("risk", "风险", rs, rev))

    W = dict(config.SCORE_WEIGHTS)
    # 指数 / 数据缺失时，把该维度权重按比例让给其它维度，避免拉低总分
    if not (chip and chip.get("ok")):
        W.pop("chip", None)
    if not (chan and chan.get("ok")):
        W.pop("chan", None)

    num = sum(W.get(k, 0.0) * s for k, _, s, _ in dims)
    den = sum(W.get(k, 0.0) for k, _, s, _ in dims) or 1.0
    weighted = num / den
    score = 100.0 * _th(KAPPA * weighted)

    abs_num = sum(W.get(k, 0.0) * abs(s) for k, _, s, _ in dims)
    agreement = abs(num) / abs_num if abs_num > 0 else 0.0

    adx = _last(ind["adx"], 20.0)
    g = min(1.0, adx / 30.0)
    n = len(bars)
    conf = agreement * (1 - math.exp(-n / 80.0)) * (0.55 + 0.45 * g)

    out_dims = []
    for k, name, s, ev in dims:
        na = W.get(k, 0) == 0
        if k == "risk":
            tag = "低风险" if s > 0.30 else ("中风险" if s > -0.30 else "高风险")
        else:
            tag = "不适用" if na else _dim_tag(s)
        out_dims.append({
            "key": k, "name": name,
            "score": round(s, 4),
            "score100": round(s * 100, 1),
            "weight": W.get(k, 0),
            "tag": tag,
            "side": "na" if na else ("bull" if s > 0.15 else ("bear" if s < -0.15 else "neutral")),
            "evidence": [e for e in ev if e],
        })

    lv = _level(score)
    bull_n = sum(1 for d in out_dims if d["side"] == "bull")
    bear_n = sum(1 for d in out_dims if d["side"] == "bear")

    return {
        "score": round(score, 1),
        "level": lv,
        "confidence": round(conf * 100, 1),
        "agreement": round(agreement * 100, 1),
        "weighted": round(weighted, 4),
        "dimensions": out_dims,
        "bull_dims": bull_n, "bear_dims": bear_n,
        "phase": phase_info.get("phase") if phase_info else None,
    }


# ============================================================ 关键价位

def key_levels(bars, ind, chip, chan):
    close = ind["_close"][-1]
    atr = _last(ind["atr"], close * 0.02)
    cands_sup = []
    cands_res = []

    if chip and chip.get("ok"):
        if chip.get("main_zone"):
            cands_sup.append(("主力筹码区下沿", chip["main_zone"]["low"]))
            cands_res.append(("主力筹码区上沿", chip["main_zone"]["high"]))
        cands_sup.append(("主力成本", chip["main_cost"]))
        cands_res.append(("散户成本(解套位)", chip["retail_cost"]))
        cands_sup.append(("90%成本下沿", chip["p10"]))
        cands_res.append(("90%成本上沿", chip["p90"]))

    if chan and chan.get("ok") and chan.get("cur_zs"):
        cands_sup.append(("中枢下沿 ZD", chan["cur_zs"]["zd"]))
        cands_res.append(("中枢上沿 ZG", chan["cur_zs"]["zg"]))

    for p, key in ((20, "ma20"), (60, "ma60")):
        v = _last(ind[key])
        if v:
            cands_sup.append(("MA%d" % p, v))
            cands_res.append(("MA%d" % p, v))

    lows = ind["_low"]
    highs = ind["_high"]
    if len(lows) >= 20:
        cands_sup.append(("20日低点", min(lows[-20:])))
        cands_res.append(("20日高点", max(highs[-20:])))
    if len(lows) >= 60:
        cands_sup.append(("60日低点", min(lows[-60:])))
        cands_res.append(("60日高点", max(highs[-60:])))

    sup = sorted({round(v, 3): n for n, v in cands_sup if v and v < close * 0.999}.items(),
                 key=lambda x: -x[0])[:3]
    res = sorted({round(v, 3): n for n, v in cands_res if v and v > close * 1.001}.items(),
                 key=lambda x: x[0])[:3]

    # 名称映射（同价位保留第一个名称）
    name_sup = {}
    for n, v in cands_sup:
        if v and v < close * 0.999:
            name_sup.setdefault(round(v, 3), n)
    name_res = {}
    for n, v in cands_res:
        if v and v > close * 1.001:
            name_res.setdefault(round(v, 3), n)

    supports = [{"price": p, "label": name_sup.get(p, ""), "dist_pct": round((p / close - 1) * 100, 2)}
                for p, _ in sup]
    resists = [{"price": p, "label": name_res.get(p, ""), "dist_pct": round((p / close - 1) * 100, 2)}
               for p, _ in res]

    stop_raw = supports[0]["price"] * 0.985 if supports else close - atr * 1.8
    stop = max(stop_raw, close - atr * 2.2)
    stop = min(stop, close * 0.995)
    tgt_raw = resists[0]["price"] if resists else close + atr * 2.8
    target = max(tgt_raw, close + atr * 2.2)

    return {
        "supports": supports, "resists": resists,
        "stop": round(stop, 3), "target": round(target, 3),
        "atr": round(atr, 3),
        "risk_reward": round((target - close) / max(close - stop, 1e-6), 2),
    }


# ============================================================ 操作建议

def advise(score_res, chip, chan, phase_info, levels):
    s = score_res["score"]
    lv = score_res["level"]["name"]
    conf = score_res["confidence"]
    phase = (phase_info or {}).get("phase", "横盘")

    if s >= 55 and conf >= 55:
        act, stance = "积极", "多头共振，趋势与筹码同向"
        advice = "多维度共振向上，可持股待涨；回踩 5/10 日线不破可加仓。"
    elif s >= 35:
        act, stance = "偏多", "多数维度转多，但仍有分歧"
        advice = "趋势转强但一致性不足，建议轻仓参与，突破关键压力再加。"
    elif s >= 12:
        act, stance = "观察偏多", "局部转强"
        advice = "有转强迹象，等放量突破确认，不追高。"
    elif s > -12:
        act, stance = "观望", "多空均衡"
        advice = "方向不明，空仓或极轻仓等待；等放量选择方向。"
    elif s > -35:
        act, stance = "偏空", "多数维度走弱"
        advice = "反弹减仓为主，不轻易抄底。"
    elif s > -55:
        act, stance = "看空", "趋势与筹码同步走坏"
        advice = "空头占优，逢反弹离场，跌破支撑严格止损。"
    else:
        act, stance = "回避", "多维度共振向下"
        advice = "坚决回避，不接飞刀。"

    extra = []
    if phase == "派发":
        extra.append("当前处于派发阶段，任何反弹都应视为减仓机会")
    elif phase == "吸筹":
        extra.append("当前处于吸筹阶段，适合在主力成本区附近分批布局")
    elif phase == "拉升":
        extra.append("当前处于拉升阶段，持股为主，破 10 日线减仓")
    elif phase == "洗盘":
        extra.append("当前处于洗盘阶段，不追跌不恐慌，看支撑是否守住")
    elif phase == "下跌":
        extra.append("当前处于下跌阶段，等缩量止跌 + 底分型再考虑")

    if chip and chip.get("ok"):
        if chip["profit_ratio"] > 92:
            extra.append("获利盘 %.0f%%，兑现压力大" % chip["profit_ratio"])
        elif chip["profit_ratio"] < 8:
            extra.append("获利盘仅 %.0f%%，超跌反弹条件具备" % chip["profit_ratio"])
        if chip["control"] > 60:
            extra.append("主力控盘度 %.0f%%，筹码高度集中" % chip["control"])

    if chan and chan.get("ok") and chan.get("position") == "中枢下方":
        extra.append("价格在中枢下方，等三卖风险释放完毕")

    rr = levels["risk_reward"]
    if rr < 1.0:
        extra.append("盈亏比仅 %.2f，位置不佳" % rr)

    return {
        "action": act, "stance": stance,
        "advice": advice, "notes": extra,
        "stop": levels["stop"], "target": levels["target"],
    }
