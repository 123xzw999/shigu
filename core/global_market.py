# -*- coding: utf-8 -*-
"""
外围市场 · global_market.py
===========================
覆盖：美股指数 / 美股龙头 / 港股 / 日经·欧洲 / 外汇 / 商品（金银油铜）

两个核心产出：

1. **GRAI · Global Risk Appetite Index（全球风险偏好指数）**
   把分散的外围涨跌压缩成一个 -100~+100 的标量，并给出对 A 股的传导判断。

       z_i  = 涨跌幅_i / 典型日波动_i          按各市场波动特性标准化
       GRAI = 100 · tanh( Σ w_i · z_i + 0.15·(pos52_us - 0.5)·2 )

   权重设计逻辑：
       美股    +0.34   全球风险资产定价锚
       恒生    +0.20   与 A 股联动最紧
       日经    +0.10   亚太风险偏好
       美元人民币 -0.16  人民币贬值 → 外资流出压力（反向）
       黄金    -0.10   避险资产，涨 = 风险偏好下降（反向）
       原油    +0.06   需求侧指标
       伦铜    +0.04   工业需求

2. **单标的分析**：有 K 线就走完整技术分析（趋势/动量/位置/风险四维），
   只有快照的（外汇、部分指数）用快照位置分位降级评估。
"""

import math
import datetime

from . import config
from . import sina
from . import indicators as ta


def _th(x):
    return math.tanh(max(-8.0, min(8.0, x)))


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _last(series, default=0.0):
    if not series:
        return default
    v = series[-1]
    return default if v is None else v


def _level(score):
    """GRAI 风险偏好标签"""
    if score >= 55:
        return {"name": "强 Risk-On", "key": "strong_on", "color": "#e01b1b"}
    if score >= 20:
        return {"name": "偏 Risk-On", "key": "on", "color": "#ef4b4b"}
    if score > -20:
        return {"name": "中性", "key": "neutral", "color": "#8a8a8a"}
    if score > -55:
        return {"name": "偏 Risk-Off", "key": "off", "color": "#1ba784"}
    return {"name": "强 Risk-Off", "key": "strong_off", "color": "#0d8a6a"}


def _dir_level(score):
    """单标的涨跌方向标签（不要和 GRAI 的 Risk-On 混用）"""
    if score >= 55:
        return {"name": "强多", "key": "strong_bull", "color": "#e01b1b"}
    if score >= 20:
        return {"name": "偏多", "key": "bull", "color": "#ef4b4b"}
    if score > -20:
        return {"name": "中性", "key": "neutral", "color": "#8a8a8a"}
    if score > -55:
        return {"name": "偏空", "key": "bear", "color": "#1ba784"}
    return {"name": "强空", "key": "strong_bear", "color": "#0d8a6a"}


# ============================================================ 分组快照

_GROUPS = [
    ("us_idx", "美股指数", config.US_INDICES),
    ("hk_idx", "港股指数", config.HK_INDICES),
    ("gl_idx", "其他指数", config.OTHER_INDICES),
    ("us_stock", "美股龙头", config.US_STOCKS),
    ("hk_stock", "港股龙头", config.HK_STOCKS),
    ("fx", "外汇", config.FX_LIST),
    ("commodity", "商品", config.COMMODITY_LIST),
]

_DECIMALS = {
    "fx_susdcny": 4, "fx_seurusd": 5, "fx_susdjpy": 3,
    "fx_sgbpusd": 5, "fx_saudusd": 5,
    "hf_GC": 2, "hf_SI": 3, "hf_CL": 2, "hf_CAD": 1,
    "nf_AU0": 2, "nf_RB0": 1,
}


def _decimals(key, price):
    if key in _DECIMALS:
        return _DECIMALS[key]
    if price >= 10000:
        return 1
    if price >= 1000:
        return 2
    if price >= 10:
        return 2
    return 3


def snapshot():
    """拉全部外围行情并分组"""
    keys = []
    for _, _, lst in _GROUPS:
        keys.extend(k for k, _, _ in lst)
    quotes = sina.fetch_global(keys)

    groups = []
    for gkey, gname, lst in _GROUPS:
        items = []
        for key, name, mkt in lst:
            q = quotes.get(key)
            if not q:
                continue
            price = q.get("price") or 0
            items.append({
                "symbol": key,
                "name": q.get("name") or name,
                "market": mkt,
                "price": round(price, _decimals(key, price)),
                "change": round(q.get("change") or 0, _decimals(key, price)),
                "change_pct": round(q.get("change_pct") or 0, 2),
                "high": q.get("high") or 0,
                "low": q.get("low") or 0,
                "open": q.get("open") or 0,
                "prev_close": q.get("prev_close") or 0,
                "pos52": q.get("pos52"),
                "pos_day": q.get("pos_day"),
                "time": q.get("time") or "",
                "date": q.get("date") or "",
            })
        if items:
            groups.append({"key": gkey, "name": gname, "items": items})

    risk = risk_appetite(quotes)
    return {
        "ok": True,
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "groups": groups,
        "risk": risk,
        "total": sum(len(g["items"]) for g in groups),
    }


# ============================================================ 风险偏好

_TYPICAL_VOL = {
    "us": 0.90, "hk": 1.20, "jp": 1.20,
    "fx_cny": 0.15, "gold": 0.90, "oil": 2.00, "copper": 1.20,
}


def risk_appetite(quotes):
    """GRAI 全球风险偏好指数"""
    def pct(key):
        q = quotes.get(key)
        return (q.get("change_pct") or 0.0) if q else None

    us_list = [pct("gb_$dji"), pct("gb_$ixic"), pct("gb_$inx")]
    us_vals = [x for x in us_list if x is not None]
    us = sum(us_vals) / len(us_vals) if us_vals else None
    hk = pct("rt_hkHSI")
    jp = pct("int_nikkei")
    cny = pct("fx_susdcny")
    gold = pct("hf_GC")
    oil = pct("hf_CL")
    cu = pct("hf_CAD")

    comps = []
    total = 0.0

    def add(name, val, vol, w, key=None):
        nonlocal total
        if val is None:
            return
        z = val / vol
        contrib = w * z
        total += contrib
        comps.append({
            "key": key or name, "name": name,
            "pct": round(val, 2), "z": round(z, 2),
            "weight": w, "contrib": round(contrib, 4),
        })

    add("美股", us, _TYPICAL_VOL["us"], 0.34, "us")
    add("恒生", hk, _TYPICAL_VOL["hk"], 0.20, "hk")
    add("日经", jp, _TYPICAL_VOL["jp"], 0.10, "jp")
    add("美元人民币", cny, _TYPICAL_VOL["fx_cny"], -0.16, "cny")
    add("黄金", gold, _TYPICAL_VOL["gold"], -0.10, "gold")
    add("原油", oil, _TYPICAL_VOL["oil"], 0.06, "oil")
    add("伦铜", cu, _TYPICAL_VOL["copper"], 0.04, "copper")

    # 美股位置修正：在 52 周高位说明风险偏好本就偏强
    q_us = quotes.get("gb_$inx") or quotes.get("gb_$dji")
    pos = (q_us or {}).get("pos52")
    if pos is not None:
        bonus = 0.15 * (pos / 100.0 - 0.5) * 2
        total += bonus
        comps.append({
            "key": "pos", "name": "美股位置", "pct": pos,
            "z": round(bonus, 2), "weight": 0.15, "contrib": round(bonus, 4),
        })

    score = 100.0 * _th(1.35 * total)
    lv = _level(score)

    # ---- 传导信号
    signals = []

    def sig(level, text):
        signals.append({"level": level, "text": text})

    if us is not None:
        if us <= -1.5:
            sig("bad", "隔夜美股均值下跌 %.2f%%，A股开盘情绪承压" % us)
        elif us >= 1.5:
            sig("good", "隔夜美股均值上涨 %.2f%%，A股开盘情绪偏暖" % us)
    if hk is not None:
        if hk <= -2.0:
            sig("bad", "恒生指数下跌 %.2f%%，港股与A股联动承压" % hk)
        elif hk >= 2.0:
            sig("good", "恒生指数上涨 %.2f%%，南向情绪回暖" % hk)
    if gold is not None and gold >= 1.5:
        sig("warn", "黄金上涨 %.2f%%，避险情绪升温" % gold)
    if gold is not None and gold <= -2.0:
        sig("good", "黄金下跌 %.2f%%，避险资金撤出，风险偏好回升" % abs(gold))
    if cny is not None:
        if cny >= 0.30:
            sig("bad", "人民币贬值 %.2f%%，关注外资流出压力" % cny)
        elif cny <= -0.30:
            sig("good", "人民币升值 %.2f%%，有利于外资流入" % abs(cny))
    if oil is not None and abs(oil) >= 3.0:
        sig("warn", "原油%s %.2f%%，通胀预期波动加大" % ("上涨" if oil > 0 else "下跌", abs(oil)))

    if score >= 20:
        ashare = "外围风险偏好偏强，A股情绪面有支撑，可关注开盘承接力度。"
    elif score > -20:
        ashare = "外围情绪中性，对A股影响有限，回归内部量价与筹码结构。"
    else:
        ashare = "外围风险偏好偏弱，注意A股低开风险，控制仓位。"

    return {
        "score": round(score, 1),
        "level": lv,
        "components": comps,
        "signals": signals[:6],
        "a_share": ashare,
        "raw": round(total, 4),
    }


# ============================================================ 单标的分析

def analyze(symbol, quote=None):
    """外围单标的分析。有 K 线走技术分析，无 K 线走快照评估。"""
    key = symbol
    q = quote or (sina.fetch_global([key]).get(key))
    if not q:
        return {"ok": False, "symbol": key, "reason": "外围行情获取失败"}

    bars = sina.fetch_global_kline(key)
    name = q.get("name") or key
    dec = _decimals(key, q.get("price") or 0)

    dims = []
    view = None
    ma_lines = {}

    if bars and len(bars) >= 30:
        ind = ta.compute_all(bars, 0)
        close = ind["_close"]
        price = close[-1]
        ma5, ma20, ma60 = _last(ind["ma5"], price), _last(ind["ma20"], price), _last(ind["ma60"], price)
        rsi = _last(ind["rsi14"], 50.0)
        hist = _last(ind["macd"])
        atr = _last(ind["atr"], price * 0.02) or price * 0.02
        natr = _last(ind["natr"], 2.0)
        beta = ta.slope([math.log(max(c, 1e-9)) for c in close[-25:]], 20)

        t1 = (ma5 / ma20 - 1) * 100 if ma20 else 0.0
        t2 = (ma20 / ma60 - 1) * 100 if ma60 else 0.0
        T = _clamp(_th(0.35 * t1 + 0.25 * t2 + 3.0 * beta))
        M = _clamp(_th((rsi - 50) / 20.0 + hist / (atr * 0.9 if atr else 1)))
        P = _clamp(_th(((q.get("pos52") or 50) / 100.0 - 0.5) * 3.0))
        R = _clamp(-_th((natr - 2.6) / 2.6))
        # 当日方向单独成维：避免「中期多头 + 今天大跌」被均线掩盖
        D = _clamp(_th((q.get("change_pct") or 0.0) / 1.2))

        dims = [
            ("当日", D, ["涨跌 %+.2f%%" % (q.get("change_pct") or 0),
                       "日内位置 %s%%" % (q.get("pos_day") if q.get("pos_day") is not None else "—")]),
            ("趋势", T, ["MA5/MA20 %+.2f%%" % t1, "MA20/MA60 %+.2f%%" % t2,
                       "20日回归斜率 %+.3f%%/日" % beta]),
            ("动量", M, ["RSI14 %.1f" % rsi, "MACD 柱 %.3f" % hist, "近5日 %+.2f%%" %
                       ((close[-1] / close[-6] - 1) * 100 if len(close) > 6 else 0)]),
            ("位置", P, ["52周分位 %s%%" % (q.get("pos52") if q.get("pos52") is not None else "—"),
                       "距 52 周高 %.2f%%" % (((price / (q.get("w52_high") or price)) - 1) * 100)
                       if q.get("w52_high") else "—"]),
            ("风险", R, ["ATR 占价 %.2f%%" % natr]),
        ]
        for p in config.MA_PERIODS[:4]:
            ma_lines["ma%d" % p] = ind.get("ma%d" % p)
        view = {
            "scale": 240, "scale_name": "日线",
            "bars": [{"d": b["day"], "o": round(b["open"], dec), "h": round(b["high"], dec),
                      "l": round(b["low"], dec), "c": round(b["close"], dec),
                      "v": round(b["volume"], 0)} for b in bars[-320:]],
            "ind": {k: v[-320:] if v else [] for k, v in {
                "ma5": ind.get("ma5"), "ma10": ind.get("ma10"),
                "ma20": ind.get("ma20"), "ma60": ind.get("ma60"),
                "boll_up": ind.get("boll_up"), "boll_mid": ind.get("boll_mid"),
                "boll_low": ind.get("boll_low"), "dif": ind.get("dif"),
                "dea": ind.get("dea"), "macd": ind.get("macd"),
                "rsi14": ind.get("rsi14"), "k": ind.get("k"),
                "d": ind.get("d"), "j": ind.get("j"),
            }.items()},
            "chan": None,
        }
        weights = {"当日": 0.20, "趋势": 0.30, "动量": 0.25, "位置": 0.15, "风险": 0.10}
    else:
        chg = q.get("change_pct") or 0.0
        pos52 = q.get("pos52")
        posd = q.get("pos_day")
        D = _clamp(_th(chg / 1.2))
        T = _clamp(_th(chg / 1.5))
        M = _clamp(_th(chg / 1.0))
        P = _clamp(_th(((pos52 or 50) / 100.0 - 0.5) * 3.0))
        R = 0.0
        dims = [
            ("当日", D, ["涨跌 %+.2f%%" % chg, "日内位置 %s%%" % (posd if posd is not None else "—")]),
            ("趋势", T, ["无历史K线，按当日方向评估"]),
            ("动量", M, ["无历史K线，按当日方向评估"]),
            ("位置", P, ["52周分位 %s%%" % (pos52 if pos52 is not None else "—")]),
            ("风险", R, ["外汇/指数类无K线，风险维度不适用"]),
        ]
        weights = {"当日": 0.35, "趋势": 0.25, "动量": 0.20, "位置": 0.20, "风险": 0.0}

    num = sum(weights[n] * v for n, v, _ in dims)
    den = sum(weights[n] for n, _, _ in dims) or 1.0
    score = 100.0 * _th(1.9 * (num / den))
    lv = _dir_level(score)

    def tag(v):
        if v > 0.45:
            return "强多"
        if v > 0.15:
            return "偏多"
        if v >= -0.15:
            return "中性"
        if v > -0.45:
            return "偏空"
        return "强空"

    out_dims = []
    for n, v, ev in dims:
        if n == "风险":
            tg = "低风险" if v > 0.15 else ("高风险" if v < -0.15 else "中风险")
        else:
            tg = tag(v)
        out_dims.append({
            "name": n, "score": round(v, 4), "score100": round(v * 100, 1),
            "tag": tg,
            "side": "bull" if v > 0.15 else ("bear" if v < -0.15 else "neutral"),
            "evidence": [e for e in ev if e],
        })

    return {
        "ok": True,
        "symbol": key,
        "name": name,
        "kind": "global",
        "market": q.get("market", ""),
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "quote": {
            "name": name, "price": round(q.get("price") or 0, dec),
            "change": round(q.get("change") or 0, dec),
            "change_pct": round(q.get("change_pct") or 0, 2),
            "open": round(q.get("open") or 0, dec),
            "prev_close": round(q.get("prev_close") or 0, dec),
            "high": round(q.get("high") or 0, dec),
            "low": round(q.get("low") or 0, dec),
            "volume": q.get("volume") or 0, "amount": q.get("amount") or 0,
            "date": q.get("date") or "", "time": q.get("time") or "",
            "kind": "global", "bids": [], "asks": [],
        },
        "view": view,
        "analysis": {
            "score": {
                "score": round(score, 1), "level": lv,
                "confidence": 65.0 if bars else 40.0,
                "agreement": 70.0, "weighted": round(num / den, 4),
                "dimensions": out_dims,
                "bull_dims": sum(1 for d in out_dims if d["side"] == "bull"),
                "bear_dims": sum(1 for d in out_dims if d["side"] == "bear"),
            },
            "chan": None, "chip": None,
            "phase": {"phase": "外围市场", "confidence": 0.0, "detail": {}, "features": {},
                      "desc": "外围市场不做主力筹码与阶段分析"},
            "segments": [],
            "patterns": {"score": 0, "bull": 0, "bear": 0, "text": "外围市场不做K线形态分析", "list": []},
            "levels": {"supports": [], "resists": [], "stop": 0, "target": 0,
                       "atr": 0, "risk_reward": 0},
            "advice": {
                "action": "参考" if score > -20 else "谨慎",
                "stance": "外围市场作为 A 股的外部环境参考",
                "advice": ("外围偏强，可作为 A 股情绪面的正向参考。" if score > 20 else
                           "外围偏弱，注意对 A 股开盘的拖累。" if score < -20 else
                           "外围中性，A 股走势更多取决于内部量价结构。"),
                "notes": ["外围市场无流通股本数据，不做筹码/主力阶段分析"],
                "stop": 0, "target": 0,
            },
            "summary": {
                "trend": "日线" if bars else "快照",
                "position": "52周分位 %s%%" % (q.get("pos52") if q.get("pos52") is not None else "—"),
                "periods": {}, "phase": "外围市场",
                "phase_conf": 0, "bars": len(bars) if bars else 0,
                "range": [bars[0]["day"], bars[-1]["day"]] if bars else [],
            },
        },
    }


# ============================================================ 检索

def match(keyword):
    """在外围标的里按代码/名称模糊匹配"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return []
    out = []
    for gkey, gname, lst in _GROUPS:
        for key, name, mkt in lst:
            if kw in key.lower() or kw in name.lower():
                out.append({"symbol": key, "code": key, "name": name,
                            "kind": "global", "market": gname})
    return out[:10]


def all_symbols():
    return [k for _, _, lst in _GROUPS for k, _, _ in lst]
