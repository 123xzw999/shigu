# -*- coding: utf-8 -*-
"""
分析引擎 · engine.py
====================
把数据抓取、指标计算、缠论、筹码、主力识别、形态、评分串成一条流水线。

输出结构（前端直接消费）：
{
  ok, symbol, name, kind, market, updated,
  quote:   实时行情快照
  view:    {scale, bars, ind, chan, chip}   —— 绘图用（裁剪到最近 320 根）
  analysis:{
     score, chan, chip, phase, segments, patterns, levels, advice, summary
  }
}
"""

import time
import datetime

from . import config
from . import sina
from . import indicators as ta
from . import chan as chan_mod
from . import chip as chip_mod
from . import wyckoff
from . import patterns as pat_mod
from . import scoring
from . import turning
from . import fund as fund_mod
from . import global_market

VIEW_BARS = 320          # 前端绘图根数
SCALES = {5: "5分钟", 15: "15分钟", 30: "30分钟", 60: "60分钟",
          240: "日线", 1200: "周线", 7200: "月线"}
LONG_SCALE_LEN = {1200: 400, 7200: 240}   # 周/月线一次拉多少根
# 每根K线代表多少个交易日（A股一天 240 分钟），用于把波动率拉到同一把尺子上
PERIOD_DAYS = {5: 5 / 240, 15: 15 / 240, 30: 30 / 240, 60: 60 / 240,
               240: 1, 1200: 5, 7200: 21}


def _analysis_bars(symbol, scale, daily):
    """
    选「分析基准」K线。日/周/月/分钟各自独立走完整分析；
    不足 40 根时回退到日线（新股、停牌、指数月线太短都会触发）。
    """
    if not scale or scale == 240:
        return daily, 240
    n = LONG_SCALE_LEN.get(scale) or config.KLINE_LEN_MIN
    bars = sina.fetch_kline(symbol, scale, n)
    if len(bars) < 40:
        return daily, 240
    return bars, scale


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _slice(series, n):
    return series[-n:] if len(series) > n else series


def attach_fund_analysis(d, bars, info=None):
    """
    给基金（场内 ETF/LOF + 场外）附加主动/被动专项分析。
    直接在 d['analysis']['fund'] 上挂结果。
    """
    try:
        meta = fund_mod.classify(d["symbol"], d.get("name", ""), info)
        bench = fund_mod.fetch_benchmark(meta["benchmark"])
        m = fund_mod.metrics(bars, bench)
        sc = fund_mod.score(meta, m) if m else None
        style = fund_mod.style_judge(meta, m) if m else None
        d["analysis"]["fund"] = {
            "meta": meta,
            "metrics": m,
            "score": sc,
            "style": style,
        }
        if meta["type_name"]:
            d["fund_type"] = meta["type_name"]
            d["is_passive"] = meta["passive"]
    except Exception as e:                          # noqa: BLE001
        d["analysis"]["fund"] = {"error": str(e)}
    return d


def _shift_index(obj, offset):
    """把缠论结构里的 bar 索引整体平移（裁剪后映射）"""
    return None


def _pack_view(bars, ind, chan, scale, tr=None):
    """裁剪到最近 VIEW_BARS 根，并返回绘图所需数据"""
    n = len(bars)
    k = min(VIEW_BARS, n)
    off = n - k

    view_bars = []
    for b in bars[off:]:
        view_bars.append({
            "d": b["day"], "o": round(b["open"], 3), "h": round(b["high"], 3),
            "l": round(b["low"], 3), "c": round(b["close"], 3),
            "v": round(b["volume"], 0),
        })

    keys = ["ma5", "ma10", "ma20", "ma60", "ma120",
            "boll_up", "boll_mid", "boll_low",
            "dif", "dea", "macd", "k", "d", "j",
            "rsi14", "vr", "obv", "atr", "boll_w"]
    view_ind = {}
    for kk in keys:
        if kk in ind:
            view_ind[kk] = _slice(ind[kk], k)

    # 缠论叠加层：索引平移到裁剪窗口内
    ch = None
    if chan and chan.get("ok"):
        bis = []
        for b in chan["bis"]:
            s, e = b["start_bar"] - off, b["end_bar"] - off
            if e < 0 or s > k - 1:
                continue
            bis.append({
                "s": max(s, 0), "e": min(e, k - 1),
                "sp": round(b["start_price"], 3), "ep": round(b["end_price"], 3),
                "dir": b["direction"],
            })
        zs = []
        for z in chan["zhongshu"]:
            s, e = z["start_bar"] - off, z["end_bar"] - off
            if e < 0 or s > k - 1:
                continue
            zs.append({"s": max(s, 0), "e": min(e, k - 1),
                       "zd": round(z["zd"], 3), "zg": round(z["zg"], 3)})
        sigs = []
        for sg in chan["signals"]:
            i = sg["bar"] - off
            if 0 <= i < k:
                sigs.append({"i": i, "t": sg["type"], "side": sg["side"],
                             "p": round(sg["price"], 3), "s": sg["strength"]})
        ch = {"bis": bis, "zhongshu": zs, "signals": sigs,
              "position": chan.get("position"), "trend": chan.get("trend")}

    # 转折点叠加层：把 turning 的拐点索引平移到裁剪窗口内
    tv = None
    if tr and tr.get("ok"):
        turns = []
        for t in tr.get("turns", []):
            i = t["i"] - off
            if 0 <= i < k:
                turns.append({"i": i, "t": t["type"], "p": round(t["price"], 3)})
        ph = []
        for p in tr.get("phases", []):
            ss, ee = p["start"] - off, p["end"] - off
            if ee < 0 or ss > k - 1:
                continue
            ph.append({"s": max(ss, 0), "e": min(ee, k - 1), "type": p["type"]})
        tv = {"turns": turns, "phases": ph,
              "phase": tr.get("phase"), "rev": tr.get("rev")}

    return {"scale": scale, "scale_name": SCALES.get(scale, str(scale)),
            "bars": view_bars, "ind": view_ind, "chan": ch, "turning": tv}


# ============================================================ 场外基金

def analyze_offund(symbol, quote=None):
    """场外基金：用历史净值构造序列做趋势/动量分析（无成交量，跳过筹码与量能）"""
    code = symbol.replace("f_", "")
    quote = quote or (sina.fetch_quotes([symbol]).get(symbol) or {})
    navs = sina.fetch_fund_nav_history(code, 500)
    info = sina.fetch_fund_info(code)
    if not navs or len(navs) < 30:
        return {"ok": False, "symbol": symbol, "name": quote.get("name", code),
                "kind": "ofund", "reason": "历史净值数据不足", "quote": quote}

    bars = []
    prev = navs[0]["nav"]
    for r in navs:
        nav = r["nav"]
        bars.append({"day": r["day"], "open": prev, "high": max(prev, nav),
                     "low": min(prev, nav), "close": nav, "volume": 0.0})
        prev = nav

    close = [b["close"] for b in bars]
    high = [b["high"] for b in bars]
    low = [b["low"] for b in bars]
    vol = [1.0] * len(bars)

    ma5, ma20, ma60 = ta.sma(close, 5), ta.sma(close, 20), ta.sma(close, 60)
    rsi14 = ta.rsi(close, 14)
    dif, dea, hist = ta.macd(close)
    atr_ = ta.atr(high, low, close, 14)
    hv = ta.hv(close, 20)

    def last(s, d=0.0):
        if not s or s[-1] is None:
            return d
        return s[-1]

    px = close[-1]
    chg1 = (px / close[-2] - 1) * 100 if len(close) > 1 else 0
    chg20 = (px / close[-21] - 1) * 100 if len(close) > 21 else 0
    chg60 = (px / close[-61] - 1) * 100 if len(close) > 61 else 0
    chg120 = (px / close[-121] - 1) * 100 if len(close) > 121 else 0
    chg250 = (px / close[-251] - 1) * 100 if len(close) > 251 else 0

    peak = max(close)
    dd = (peak - px) / peak * 100
    w = close[-250:]
    pk = -1e9
    mdd = 0.0
    for c in w:
        pk = max(pk, c)
        mdd = max(mdd, (pk - c) / pk)

    # 简化评分
    s_trend = scoring._th(0.4 * (last(ma5, px) / last(ma20, px) - 1) * 100
                          + 0.3 * (last(ma20, px) / last(ma60, px) - 1) * 100)
    s_mom = scoring._th((last(rsi14, 50) - 50) / 20 + last(hist) / max(last(atr_, 0.01), 0.01) * 0.4)
    s_risk = -scoring._th((mdd - 0.15) * 3)
    score = 100 * scoring._th(2.2 * (0.45 * s_trend + 0.35 * s_mom + 0.20 * s_risk))
    lv = scoring._level(score)

    dims = [
        {"key": "trend", "name": "净值趋势", "score": round(s_trend, 4),
         "score100": round(s_trend * 100, 1), "weight": 0.45, "tag": scoring._dim_tag(s_trend),
         "side": "bull" if s_trend > 0.15 else ("bear" if s_trend < -0.15 else "neutral"),
         "evidence": ["MA5 %s MA20" % ("高于" if last(ma5, px) > last(ma20, px) else "低于"),
                      "MA20 %s MA60" % ("高于" if last(ma20, px) > last(ma60, px) else "低于"),
                      "近20日 %+.2f%%" % chg20]},
        {"key": "momentum", "name": "净值动量", "score": round(s_mom, 4),
         "score100": round(s_mom * 100, 1), "weight": 0.35, "tag": scoring._dim_tag(s_mom),
         "side": "bull" if s_mom > 0.15 else ("bear" if s_mom < -0.15 else "neutral"),
         "evidence": ["RSI14 %.1f" % last(rsi14, 50), "MACD 柱 %.5f" % last(hist)]},
        {"key": "risk", "name": "回撤风险", "score": round(s_risk, 4),
         "score100": round(s_risk * 100, 1), "weight": 0.20, "tag": scoring._dim_tag(s_risk),
         "side": "bull" if s_risk > 0.15 else ("bear" if s_risk < -0.15 else "neutral"),
         "evidence": ["距历史高点 -%.2f%%" % dd, "近250日最大回撤 %.2f%%" % (mdd * 100),
                      "年化波动 %.1f%%" % last(hv, 0)]},
    ]

    k = min(VIEW_BARS, len(bars))
    off = len(bars) - k
    view_bars = [{"d": b["day"], "o": round(b["open"], 4), "h": round(b["high"], 4),
                  "l": round(b["low"], 4), "c": round(b["close"], 4), "v": 0}
                 for b in bars[off:]]
    view_ind = {
        "ma5": _slice(ma5, k), "ma10": _slice(ta.sma(close, 10), k),
        "ma20": _slice(ma20, k), "ma60": _slice(ma60, k),
        "boll_up": _slice(ta.bbands(close, 20, 2)[0], k),
        "boll_mid": _slice(ta.bbands(close, 20, 2)[1], k),
        "boll_low": _slice(ta.bbands(close, 20, 2)[2], k),
        "dif": _slice(dif, k), "dea": _slice(dea, k), "macd": _slice(hist, k),
        "rsi14": _slice(rsi14, k),
    }

    result = {
        "ok": True, "symbol": symbol, "name": quote.get("name") or info.get("short_name", code),
        "kind": "ofund", "market": "场外基金", "updated": _now(),
        "quote": quote,
        "fund_info": info,
        "view": {"scale": 240, "scale_name": "净值曲线", "bars": view_bars,
                 "ind": view_ind, "chan": None, "nav_mode": True},
        "analysis": {
            "score": {"score": round(score, 1), "level": lv,
                      "confidence": 60.0, "agreement": 55.0,
                      "dimensions": dims, "bull_dims": 1, "bear_dims": 0,
                      "weighted": 0.0},
            "chan": None, "chip": None,
            "phase": {"phase": "基金净值走势", "confidence": 0.0,
                      "detail": {}, "features": {}},
            "segments": [],
            "patterns": {"score": 0, "bull": 0, "bear": 0, "text": "场外基金不做K线形态分析", "list": []},
            "levels": {"supports": [], "resists": [], "stop": 0, "target": 0,
                       "atr": 0, "risk_reward": 0},
            "advice": {
                "action": "定投" if score > -20 else "暂停",
                "stance": "场外基金按净值趋势操作",
                "advice": ("净值趋势向上，可维持定投；单日净值波动不代表趋势改变。"
                           if score > 0 else "净值趋势偏弱，建议降低定投频率或等待企稳。"),
                "notes": ["场外基金按 T+1 净值成交，无盘中K线，筹码/量能指标不适用"],
                "stop": 0, "target": 0,
            },
            "summary": {
                "trend": "净值 %s" % ("上行" if last(ma5, px) > last(ma20, px) else "下行"),
                "periods": {"近1日": round(chg1, 2), "近20日": round(chg20, 2),
                            "近60日": round(chg60, 2), "近120日": round(chg120, 2),
                            "近250日": round(chg250, 2)},
                "drawdown": round(dd, 2), "mdd": round(mdd * 100, 2),
                "vol": round(last(hv, 0), 2),
            },
        },
    }

    attach_fund_analysis(result, bars, info)
    return result


# ============================================================ 主入口

def analyze(symbol, scale=240, quote=None):
    symbol = sina.normalize_code(symbol)
    if not symbol:
        return {"ok": False, "reason": "代码格式无法识别"}

    # ---- 外围市场（美股 / 港股 / 外汇 / 商品）
    if sina.is_global(symbol):
        return global_market.analyze(symbol)

    if symbol.startswith("f_"):
        return analyze_offund(symbol, quote)

    quote = quote or (sina.fetch_quotes([symbol]).get(symbol) or {})
    if not quote:
        return {"ok": False, "symbol": symbol, "reason": "行情获取失败（代码不存在或网络异常）"}

    kind = quote.get("kind", "stock")

    # ---- 日线（所有深度分析都基于日线）
    daily = sina.fetch_kline(symbol, 240, config.KLINE_LEN)
    if len(daily) < 40:
        return {"ok": False, "symbol": symbol, "name": quote.get("name"),
                "kind": kind, "quote": quote,
                "reason": "日K线不足 40 根（新股或停牌），无法分析"}

    float_shares = sina.fetch_float_shares(symbol) if kind != "index" else 0.0

    # ---- 分析基准周期：日 / 周 / 月 / 分钟，各自独立走完整分析
    #      筹码始终基于日线（持仓成本是日频换手累积出来的，换成周K就失真了）
    ana_bars, ana_scale = _analysis_bars(symbol, scale, daily)
    ind = ta.compute_all(ana_bars, float_shares)

    # ---- 缠论
    ch = chan_mod.analyze(ana_bars, ind["macd"])
    if ch.get("ok"):
        ch["bars_len"] = len(ana_bars)

    # ---- 筹码（固定日线）
    cp = chip_mod.analyze(daily, float_shares) if kind != "index" else None
    if cp and cp.get("ok"):
        cp["vp"] = chip_mod.volume_profile(daily)

    # ---- 主力阶段
    phase = wyckoff.current_phase(ana_bars)
    phase["desc"] = wyckoff.PHASE_DESC.get(phase["phase"], "")
    segs = wyckoff.segment_phases(ana_bars)

    # ---- 形态
    pats = pat_mod.detect(ana_bars, lookback=8)
    pat_sum = pat_mod.summarize(pats, len(ana_bars))
    pat_sum["list"] = pats[-8:]

    # ---- 评分
    score_res = scoring.compute(ana_bars, ind, cp, ch, pat_sum, phase,
                                period_days=PERIOD_DAYS.get(ana_scale, 1.0))
    levels = scoring.key_levels(ana_bars, ind, cp, ch)
    advice = scoring.advise(score_res, cp, ch, phase, levels)

    # ---- 转折点判断（逐板块模型，纯 Python 推理）
    try:
        tr = turning.analyze(
            ana_bars,
            name=quote.get("name", ""),
            symbol=symbol,
            scale=ana_scale,
            weekly=(turning.to_weekly(daily) if ana_scale not in (240, 1200) else None),
            with_series=(ana_scale in (240, 1200)),
        )
    except Exception as e:                              # noqa: BLE001
        tr = {"ok": False, "reason": "转折判断异常：%s" % e}

    view = _pack_view(ana_bars, ind, ch, ana_scale, tr)

    # ---- 汇总
    close = [b["close"] for b in daily]

    def pct(k):
        return round((close[-1] / close[-1 - k] - 1) * 100, 2) if len(close) > k else None

    summary = {
        "trend": ch.get("trend") if ch.get("ok") else "—",
        "position": ch.get("position") if ch.get("ok") else "—",
        "periods": {"近5日": pct(5), "近20日": pct(20), "近60日": pct(60),
                    "近120日": pct(120), "近250日": pct(250)},
        "phase": phase["phase"],
        "phase_conf": phase["confidence"],
        "main_cost": cp["main_cost"] if cp else None,
        "retail_cost": cp["retail_cost"] if cp else None,
        "control": cp["control"] if cp else None,
        "profit_ratio": cp["profit_ratio"] if cp else None,
        "concentration": cp["concentration"] if cp else None,
        "turnover": (round(daily[-1]["volume"] / float_shares * 100, 2)
                     if float_shares and daily else None),
        "float_shares": float_shares,
        "bars": len(ana_bars),
        "scale": ana_scale,
        "scale_name": SCALES.get(ana_scale, "日线"),
        "daily_bars": len(daily),
        "range": [ana_bars[0]["day"], ana_bars[-1]["day"]],
        "daily_range": [daily[0]["day"], daily[-1]["day"]],
    }

    result = {
        "ok": True,
        "symbol": symbol,
        "name": quote.get("name", symbol),
        "kind": kind,
        "market": sina.market_of(symbol),
        "updated": _now(),
        "quote": quote,
        "view": view,
        "analysis_scale": ana_scale,
        "analysis_scale_name": SCALES.get(ana_scale, "日线"),
        "analysis": {
            "score": score_res,
            "chan": {
                "ok": ch.get("ok"),
                "trend": ch.get("trend"),
                "position": ch.get("position"),
                "bi_count": ch.get("bi_count"),
                "duan_count": ch.get("duan_count"),
                "zs_count": ch.get("zs_count"),
                "fractal_count": ch.get("fractal_count"),
                "cur_zs": ch.get("cur_zs"),
                "cur_bi": ch.get("cur_bi"),
                "divergences": (ch.get("divergences") or [])[-4:],
                "signals": (ch.get("signals") or [])[-8:],
                "last_signal": ch.get("last_signal"),
                "recent_signals": ch.get("recent_signals"),
                "zhongshu": ch.get("zhongshu"),
            },
            "chip": cp,
            "phase": phase,
            "segments": segs,
            "patterns": pat_sum,
            "levels": levels,
            "advice": advice,
            "turning": tr,
            "summary": summary,
        },
    }

    # 基金（场内 ETF / LOF）附加主被动专项分析
    if kind == "fund":
        attach_fund_analysis(result, daily, sina.fetch_fund_info(symbol[2:]))

    return result
