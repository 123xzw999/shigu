# -*- coding: utf-8 -*-
"""
K线形态识别 · patterns.py
=========================
覆盖 A 股实战中最常见的「主力控盘形态」。每个形态返回 [-1, 1] 的强度，
正数看涨、负数看跌，绝对值代表可靠度。

形态分四组：
  A. 单K反转（锤子/上吊/射击之星/倒锤/十字星）
  B. 双K组合（吞没/曙光初现/乌云盖顶/跳空缺口）
  C. 三K组合（早晨之星/黄昏之星/红三兵/三只乌鸦/多方炮/空方炮/上升三法）
  D. 主力特化（涨停板/一字板/长下影洗盘针/高位放量长上影/缩量十字变盘/岛形反转）
"""


def _body(b):
    return abs(b["close"] - b["open"])


def _rng(b):
    return max(b["high"] - b["low"], 1e-9)


def _up_shadow(b):
    return b["high"] - max(b["close"], b["open"])


def _dn_shadow(b):
    return min(b["close"], b["open"]) - b["low"]


def _is_bull(b):
    return b["close"] >= b["open"]


def _pos(bars, i, n=60):
    """当前在近 n 日区间中的位置：0 底部，1 顶部"""
    w = bars[max(0, i - n + 1):i + 1]
    lo = min(x["low"] for x in w)
    hi = max(x["high"] for x in w)
    return (bars[i]["close"] - lo) / (hi - lo) if hi > lo else 0.5


def _vol_ratio(bars, i, n=20):
    w = bars[max(0, i - n):i]
    if not w:
        return 1.0
    ma = sum(x["volume"] for x in w) / len(w)
    return bars[i]["volume"] / ma if ma > 0 else 1.0


def _amp(b):
    return _rng(b) / b["close"] * 100 if b["close"] else 0.0


# ------------------------------------------------------------ 形态检测

def detect(bars, lookback=8):
    """
    检测最近 lookback 根K线上的形态。
    返回 [{'name','side','strength','bar','desc','tag'}]，按 bar 升序。
    """
    out = []
    n = len(bars)
    if n < 5:
        return out
    start = max(3, n - lookback)

    def add(name, side, strength, i, desc, tag):
        # 强度带符号：看涨为正、看跌为负、中性为 0
        val = strength if side == "bull" else (-strength if side == "bear" else 0.0)
        out.append({
            "name": name, "side": side,
            "strength": round(max(-1.0, min(1.0, val)), 3),
            "bar": i, "day": bars[i]["day"],
            "desc": desc, "tag": tag,
        })

    for i in range(start, n):
        b = bars[i]
        rng = _rng(b)
        body = _body(b)
        us, ds = _up_shadow(b), _dn_shadow(b)
        p = _pos(bars, i)
        vr = _vol_ratio(bars, i)

        # ---- A. 单K
        if body / rng < 0.12 and rng / b["close"] > 0.008:
            if vr < 0.7:
                add("缩量十字星", "neutral", 0.45, i,
                    "成交萎缩至 %.2f 倍均量，多空暂时平衡，变盘前兆" % vr, "D")
            else:
                add("十字星", "neutral", 0.25, i, "开收几乎同价，多空僵持", "A")

        if ds > body * 2.0 and us < body * 0.9 and body / rng > 0.05:
            if p < 0.4:
                add("锤子线", "bull", 0.55 + (0.4 - p) * 0.6, i,
                    "长下影 %.1f%% 探底回升，低位承接明显" % (ds / b["close"] * 100), "A")
            else:
                add("上吊线", "bear", 0.45 + p * 0.4, i,
                    "高位长下影，警惕冲高回落", "A")

        if us > body * 2.0 and ds < body * 0.9 and body / rng > 0.05:
            if p > 0.6:
                add("射击之星", "bear", 0.55 + (p - 0.6) * 0.8, i,
                    "长上影 %.1f%%，上方抛压沉重" % (us / b["close"] * 100), "A")
            else:
                add("倒锤子", "bull", 0.4, i, "低位长上影试盘，抛压正在消化", "A")

        # 长下影洗盘针（主力特化）
        if ds > rng * 0.6 and vr > 1.3 and p < 0.55:
            add("放量洗盘针", "bull", 0.62, i,
                "放量下探后快速收回，典型洗盘动作（量比 %.2f）" % vr, "D")

        # 高位放量长上影（出货）
        if us > rng * 0.55 and vr > 1.5 and p > 0.65:
            add("高位放量长上影", "bear", 0.72, i,
                "高位放量冲高回落，主力借势派发嫌疑", "D")

        # ---- 涨停 / 一字板
        prev = bars[i - 1]["close"] if i > 0 else b["close"]
        chg = (b["close"] - prev) / prev * 100 if prev else 0
        if chg > 9.7 and body / rng > 0.8:
            add("涨停板", "bull", 0.75, i, "封板 %.2f%%，资金抢筹" % chg, "D")
        if chg > 9.7 and rng / b["close"] < 0.005:
            add("一字板", "bull", 0.85, i, "一字涨停，惜售情绪极致", "D")

        # ---- B. 双K
        if i >= 1:
            a = bars[i - 1]
            # 看涨吞没
            if (not _is_bull(a)) and _is_bull(b) and \
               b["close"] > a["open"] and b["open"] < a["close"] and \
               _body(b) > _body(a) * 1.1:
                add("看涨吞没", "bull", 0.6 + (0.5 - min(p, 0.5)) * 0.4, i,
                    "阳线实体完全包住前阴线，多方夺回主动权", "B")
            # 看跌吞没
            if _is_bull(a) and (not _is_bull(b)) and \
               b["close"] < a["open"] and b["open"] > a["close"] and \
               _body(b) > _body(a) * 1.1:
                add("看跌吞没", "bear", 0.6 + (max(p, 0.5) - 0.5) * 0.4, i,
                    "阴线吞没前阳线，空方接管", "B")
            # 曙光初现
            if (not _is_bull(a)) and _is_bull(b) and b["open"] < a["close"] and \
               b["close"] > (a["open"] + a["close"]) / 2 and b["close"] < a["open"]:
                add("曙光初现", "bull", 0.5, i, "低开高走收复前阴大半，见底信号", "B")
            # 乌云盖顶
            if _is_bull(a) and (not _is_bull(b)) and b["open"] > a["close"] and \
               b["close"] < (a["open"] + a["close"]) / 2 and b["close"] > a["open"]:
                add("乌云盖顶", "bear", 0.5, i, "高开低走吞掉前阳大半，见顶信号", "B")
            # 跳空缺口
            if b["low"] > a["high"] * 1.002:
                add("向上跳空", "bull", 0.5, i, "向上跳空 %.2f%%，强势" %
                    ((b["low"] - a["high"]) / a["high"] * 100), "B")
            if b["high"] < a["low"] * 0.998:
                add("向下跳空", "bear", 0.5, i, "向下跳空 %.2f%%，弱势" %
                    ((a["low"] - b["high"]) / a["low"] * 100), "B")

        # ---- C. 三K
        if i >= 2:
            a, c = bars[i - 2], bars[i - 1]
            # 早晨之星
            if (not _is_bull(a)) and _body(c) < _body(a) * 0.5 and _is_bull(b) and \
               b["close"] > (a["open"] + a["close"]) / 2 and a["close"] > b["close"]:
                add("早晨之星", "bull", 0.7, i, "阴线→星线→阳线，底部反转组合", "C")
            # 黄昏之星
            if _is_bull(a) and _body(c) < _body(a) * 0.5 and (not _is_bull(b)) and \
               b["close"] < (a["open"] + a["close"]) / 2 and a["close"] < b["close"]:
                add("黄昏之星", "bear", 0.7, i, "阳线→星线→阴线，顶部反转组合", "C")
            # 红三兵
            if all(_is_bull(x) for x in (a, c, b)) and \
               c["close"] > a["close"] and b["close"] > c["close"] and \
               all(_body(x) / _rng(x) > 0.5 for x in (a, c, b)):
                add("红三兵", "bull", 0.6, i, "三连阳稳步推高，多头排列", "C")
            # 三只乌鸦
            if all(not _is_bull(x) for x in (a, c, b)) and \
               c["close"] < a["close"] and b["close"] < c["close"] and \
               all(_body(x) / _rng(x) > 0.5 for x in (a, c, b)):
                add("三只乌鸦", "bear", 0.6, i, "三连阴节节下挫，空头主导", "C")
            # 多方炮（阳-阴-阳，第三根突破第一根）
            if _is_bull(a) and not _is_bull(c) and _is_bull(b) and \
               c["close"] > a["open"] and b["close"] > a["close"]:
                add("多方炮", "bull", 0.65, i, "阳包阴再阳，主力洗盘后二次上攻", "C")
            # 空方炮
            if (not _is_bull(a)) and _is_bull(c) and (not _is_bull(b)) and \
               c["close"] < a["open"] and b["close"] < a["close"]:
                add("空方炮", "bear", 0.65, i, "阴包阳再阴，反弹夭折", "C")
            # 上升三法
            if _is_bull(a) and all(_body(x) < _body(a) * 0.6 for x in (c,)) and \
               _is_bull(b) and b["close"] > a["close"] and \
               min(c["low"], b["low"]) > a["open"]:
                add("上升三法", "bull", 0.55, i, "大阳后小阴整理再创新高，涨势延续", "C")
            # 下降三法
            if (not _is_bull(a)) and all(_body(x) < _body(a) * 0.6 for x in (c,)) and \
               (not _is_bull(b)) and b["close"] < a["close"] and \
               max(c["high"], b["high"]) < a["open"]:
                add("下降三法", "bear", 0.55, i, "大阴后小阳反抽再创新低，跌势延续", "C")

    # ---- 岛形反转（跨 6 根）
    if n >= 8:
        for i in range(max(4, n - lookback), n):
            left_gap = bars[i - 3]["low"] > bars[i - 4]["high"] * 1.002
            right_gap = bars[i]["high"] < bars[i - 1]["low"] * 0.998
            if left_gap and right_gap:
                add("岛形反转", "bear", 0.8, i, "上下双缺口夹出孤岛，趋势反转信号", "D")
            left_gap2 = bars[i - 3]["high"] < bars[i - 4]["low"] * 0.998
            right_gap2 = bars[i]["low"] > bars[i - 1]["high"] * 1.002
            if left_gap2 and right_gap2:
                add("底部岛形反转", "bull", 0.8, i, "底部孤岛，反转向上", "D")

    # 同一根K线、同一大类只保留最强的一个，避免「上吊线+倒锤子」这类重复标注
    best = {}
    for p in out:
        k = (p["bar"], p["tag"])
        if k not in best or abs(p["strength"]) > abs(best[k]["strength"]):
            best[k] = p
    out = sorted(best.values(), key=lambda x: x["bar"])
    return out


def summarize(patterns, bars_len):
    """把形态汇总成一个 [-1,1] 的分数 + 文字结论"""
    if not patterns:
        return {"score": 0.0, "bull": 0, "bear": 0, "text": "近期无明确K线形态"}
    # 越靠近当前权重越高
    total = 0.0
    wsum = 0.0
    for p in patterns:
        age = bars_len - 1 - p["bar"]
        w = max(0.15, 1.0 - age * 0.11)
        total += p["strength"] * w
        wsum += w
    score = total / wsum if wsum else 0.0
    bull = sum(1 for p in patterns if p["side"] == "bull")
    bear = sum(1 for p in patterns if p["side"] == "bear")
    names = "、".join(dict.fromkeys(p["name"] for p in patterns[-5:]))
    if score > 0.25:
        text = "偏多形态：%s" % names
    elif score < -0.25:
        text = "偏空形态：%s" % names
    else:
        text = "形态多空交织：%s" % names
    return {"score": round(score, 4), "bull": bull, "bear": bear, "text": text}
