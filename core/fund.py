# -*- coding: utf-8 -*-
"""
基金分析 · fund.py
==================
核心是**把主动基金和被动基金分开评价** —— 它们的优劣标准完全不同：

  被动基金（ETF / 指数 / 指数增强 / ETF联接）
      看「跟得像不像」：跟踪误差、跟踪偏离度、与基准的相关性、Beta 是否接近 1
      评价公式  P = tanh((2.0 - TE)/1.5)·0.40 + tanh(超额年化/3)·0.30
                   + tanh((夏普-0.5)/1.0)·0.30

  主动基金（股票型 / 混合型 / 债券型）
      看「有没有超额能力」：Jensen's Alpha、信息比率、夏普、卡玛
      评价公式  A = tanh(Alpha年化/5)·0.40 + tanh(信息比率/1.0)·0.30
                   + tanh((夏普-0.5)/1.0)·0.30

  最终  Score = 100 · tanh(1.8 · Σ w·D)

所有比率均为年化口径，rf 取 config.FUND_RF_RATE。
"""

import math

from . import config
from . import sina
from . import indicators as ta


def _th(x):
    return math.tanh(max(-8.0, min(8.0, x)))


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _mean(a):
    return sum(a) / len(a) if a else 0.0


def _std(a):
    if len(a) < 2:
        return 0.0
    m = _mean(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / (len(a) - 1))


# ============================================================ 分类

# 场内 ETF / LOF 代码段
_PASSIVE_SH = ("510", "511", "512", "513", "515", "516", "517", "518",
               "560", "561", "562", "563", "588", "589", "501", "502", "506")
_PASSIVE_SZ = ("159", "160", "161", "162", "163", "164", "165", "166",
               "167", "168", "169")

_TYPE_NAMES = {
    "etf": "场内ETF（被动）",
    "lof": "场内LOF",
    "index": "指数基金（被动）",
    "index_enh": "指数增强（半主动）",
    "link": "ETF联接（被动）",
    "active_stock": "主动股票型",
    "active_mixed": "主动混合型",
    "active_bond": "主动债券型",
    "qdii": "QDII（跨境）",
    "money": "货币型",
    "unknown": "未分类",
}


# 基金全称里的通用词 —— 不剔掉会导致「证券投资基金」把每只基金都匹配成证券指数
_GENERIC = (
    "证券投资基金", "交易型开放式指数", "开放式证券投资基金", "发起式",
    "型证券投资基金", "基金中基金", "联接基金", "指数证券投资基金",
    "股票型证券投资基金", "混合型证券投资基金",
)


def _clean_text(text):
    for w in _GENERIC:
        text = text.replace(w, " ")
    return text


def _bench_of(name):
    text = _clean_text(name or "")
    for kw, code in config.BENCHMARKS:
        if kw in text:
            return code, kw
    return config.DEFAULT_BENCHMARK, "沪深300"


def classify(symbol, name="", info=None):
    """
    判定基金类型与主被动属性。
    返回 {type, type_name, passive, active, benchmark, bench_name, track_index}
    """
    name = name or ""
    info = info or {}
    full = info.get("full_name") or ""
    text = name + " " + full
    body = symbol.replace("f_", "")
    body = body[2:] if body[:2] in ("sh", "sz", "bj") else body

    ftype = "unknown"
    if "货币" in text:
        ftype = "money"
    elif "债券" in text or "纯债" in text or "信用债" in text:
        ftype = "active_bond"
    elif any(k in text for k in ("QDII", "全球", "海外", "美元", "纳斯达克",
                                 "标普", "恒生", "日经", "德国", "法国", "亚太")):
        ftype = "qdii"
    elif "ETF联接" in text or "联接" in text:
        ftype = "link"
    elif "指数增强" in text or "增强指数" in text:
        ftype = "index_enh"
    elif "ETF" in text:
        ftype = "etf"
    elif "LOF" in text:
        ftype = "lof"
    elif "指数" in text:
        ftype = "index"
    elif "股票" in text:
        ftype = "active_stock"
    elif any(k in text for k in ("混合", "灵活", "配置", "平衡", "成长",
                                 "价值", "精选", "优选", "优势", "回报",
                                 "主题", "轮动", "量化", "多策略")):
        ftype = "active_mixed"
    else:
        # 代码段兜底
        if symbol.startswith("sh") and body[:3] in _PASSIVE_SH:
            ftype = "etf"
        elif symbol.startswith("sz") and body[:3] in _PASSIVE_SZ:
            ftype = "lof"
        elif symbol.startswith("f_"):
            ftype = "active_mixed"
        else:
            ftype = "active_mixed"

    passive = ftype in ("etf", "index", "link", "lof")
    active = ftype in ("active_stock", "active_mixed", "active_bond")
    bench, bench_name = _bench_of(text)

    track = ""
    for kw in ("沪深300", "中证500", "中证1000", "上证50", "创业板",
               "科创50", "科创", "恒生", "纳斯达克", "标普", "黄金"):
        if kw in text:
            track = kw
            break

    return {
        "type": ftype,
        "type_name": _TYPE_NAMES.get(ftype, "未分类"),
        "passive": passive,
        "active": active,
        "semi_active": ftype == "index_enh",
        "benchmark": bench,
        "bench_name": bench_name,
        "track_index": track,
    }


# ============================================================ 基准

_bench_cache = {}


def fetch_benchmark(code):
    """取基准指数日线（A股走新浪K线，外围走全球K线）"""
    if code in _bench_cache:
        return _bench_cache[code]
    bars = []
    if code.startswith(("sh", "sz")):
        bars = sina.fetch_kline(code, 240, 400)
    else:
        bars = sina.fetch_global_kline(code, 400)
    _bench_cache[code] = bars
    return bars


def _align(fund_bars, bench_bars):
    """按日期对齐，返回 (fund_ret, bench_ret, days)"""
    bmap = {b["day"]: b["close"] for b in bench_bars}
    pairs = []
    for b in fund_bars:
        c = bmap.get(b["day"])
        if c:
            pairs.append((b["close"], c))
    if len(pairs) < 20:
        return [], [], []
    fr, br = [], []
    for i in range(1, len(pairs)):
        p0, p1 = pairs[i - 1][0], pairs[i][0]
        q0, q1 = pairs[i - 1][1], pairs[i][1]
        if p0 > 0 and q0 > 0:
            fr.append(p1 / p0 - 1)
            br.append(q1 / q0 - 1)
    return fr, br, [p[0] for p in pairs]


# ============================================================ 指标

def metrics(fund_bars, bench_bars, rf=None):
    """计算基金绩效指标（年化）"""
    rf = config.FUND_RF_RATE if rf is None else rf
    close = [b["close"] for b in fund_bars]
    n = len(close)
    if n < 30:
        return None

    rets = [close[i] / close[i - 1] - 1 for i in range(1, n) if close[i - 1] > 0]
    ann_factor = 244.0

    total_ret = close[-1] / close[0] - 1
    years = n / ann_factor
    ann_ret = (1 + total_ret) ** (1 / years) - 1 if years > 0 and total_ret > -1 else 0.0
    ann_vol = _std(rets) * math.sqrt(ann_factor)

    peak = close[0]
    mdd = 0.0
    for c in close:
        peak = max(peak, c)
        mdd = max(mdd, (peak - c) / peak if peak else 0)

    downside = [r for r in rets if r < 0]
    down_vol = _std(downside) * math.sqrt(ann_factor) if len(downside) > 1 else 0.0

    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else 0.0
    sortino = (ann_ret - rf) / down_vol if down_vol > 0 else 0.0
    calmar = ann_ret / mdd if mdd > 0 else 0.0
    win_rate = sum(1 for r in rets if r > 0) / len(rets) if rets else 0.0

    out = {
        "total_ret": round(total_ret * 100, 2),
        "ann_ret": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "mdd": round(mdd * 100, 2),
        "down_vol": round(down_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "win_rate": round(win_rate * 100, 2),
        "days": n,
        "range": [fund_bars[0]["day"], fund_bars[-1]["day"]],
    }

    # ---- 相对基准
    fr, br, _ = _align(fund_bars, bench_bars)
    if len(fr) >= 20:
        bench_total = 1.0
        for r in br:
            bench_total *= (1 + r)
        bench_ret = bench_total - 1
        byears = len(br) / ann_factor
        bench_ann = (1 + bench_ret) ** (1 / byears) - 1 if byears > 0 and bench_ret > -1 else 0.0

        ex = [a - b for a, b in zip(fr, br)]
        te = _std(ex) * math.sqrt(ann_factor)
        excess_ann = ann_ret - bench_ann
        ir = excess_ann / te if te > 0 else 0.0

        # Beta / Alpha（Jensen）
        mb, mf = _mean(br), _mean(fr)
        cov = sum((a - mf) * (b - mb) for a, b in zip(fr, br)) / max(len(fr) - 1, 1)
        var_b = sum((b - mb) ** 2 for b in br) / max(len(br) - 1, 1)
        beta = cov / var_b if var_b > 0 else 0.0
        alpha = (ann_ret - rf) - beta * (bench_ann - rf)
        corr = ta.corr(fr, br, len(fr)) if len(fr) > 2 else 0.0

        out.update({
            "bench_ret": round(bench_ret * 100, 2),
            "bench_ann": round(bench_ann * 100, 2),
            "excess": round((total_ret - bench_ret) * 100, 2),
            "excess_ann": round(excess_ann * 100, 2),
            "tracking_error": round(te * 100, 3),
            "info_ratio": round(ir, 3),
            "beta": round(beta, 3),
            "alpha": round(alpha * 100, 2),
            "corr": round(corr, 3),
        })
    return out


# ============================================================ 评分

def score(meta, m):
    """
    按主/被动分别打分。返回维度列表与综合分。
    """
    if not m:
        return None

    dims = []
    if meta["passive"]:
        te = m.get("tracking_error")
        exc = m.get("excess_ann", 0.0) or 0.0
        shp = m.get("sharpe", 0.0) or 0.0
        corr = m.get("corr", 0.0) or 0.0

        d_track = _clamp(_th(((2.0 - (te if te is not None else 3.0)) / 1.5)))
        d_exc = _clamp(_th(exc / 3.0))
        d_shp = _clamp(_th((shp - 0.5) / 1.0))

        dims = [
            ("跟踪精度", d_track, 0.40, [
                "年化跟踪误差 %.2f%%（%s）" % (te if te is not None else 0,
                                         "优秀" if (te or 9) < 1 else "良好" if (te or 9) < 2.5 else "偏大"),
                "与基准相关性 %.2f（%s）" % (corr, "高度跟踪" if corr > 0.95 else
                                       "部分跟踪" if corr > 0.8 else "偏离明显"),
                "Beta %.2f（理想接近 1）" % (m.get("beta", 0) or 0),
            ]),
            ("超额收益", d_exc, 0.30, [
                "年化超额 %+.2f%%" % exc,
                "区间超额 %+.2f%%" % (m.get("excess", 0) or 0),
                "信息比率 %.2f" % (m.get("info_ratio", 0) or 0),
            ]),
            ("风险调整", d_shp, 0.30, [
                "夏普 %.2f / 卡玛 %.2f" % (shp, m.get("calmar", 0) or 0),
                "年化波动 %.2f%%，最大回撤 %.2f%%" % (m.get("ann_vol", 0), m.get("mdd", 0)),
            ]),
        ]
    else:
        alpha = m.get("alpha", 0.0) or 0.0
        ir = m.get("info_ratio", 0.0) or 0.0
        shp = m.get("sharpe", 0.0) or 0.0

        d_alpha = _clamp(_th(alpha / 5.0))
        d_ir = _clamp(_th(ir / 1.0))
        d_shp = _clamp(_th((shp - 0.5) / 1.0))

        dims = [
            ("选股能力", d_alpha, 0.40, [
                "Jensen Alpha 年化 %+.2f%%（%s）" % (alpha, "有超额能力" if alpha > 2 else
                                                  "超额微弱" if alpha > -2 else "跑输基准"),
                "Beta %.2f（%s）" % (m.get("beta", 0) or 0,
                                    "高弹性" if (m.get("beta", 0) or 0) > 1.1 else
                                    "低弹性" if (m.get("beta", 0) or 0) < 0.9 else "中性"),
            ]),
            ("信息比率", d_ir, 0.30, [
                "信息比率 %.2f（%s）" % (ir, "优秀" if ir > 1 else "良好" if ir > 0.5 else "偏弱"),
                "年化超额 %+.2f%%，跟踪误差 %.2f%%" % (
                    m.get("excess_ann", 0) or 0, m.get("tracking_error", 0) or 0),
            ]),
            ("风险调整", d_shp, 0.30, [
                "夏普 %.2f / 卡玛 %.2f / 索提诺 %.2f" % (
                    shp, m.get("calmar", 0) or 0, m.get("sortino", 0) or 0),
                "最大回撤 %.2f%%，年化波动 %.2f%%" % (m.get("mdd", 0), m.get("ann_vol", 0)),
                "上涨天数占比 %.1f%%" % (m.get("win_rate", 0) or 0),
            ]),
        ]

    num = sum(w * v for _, v, w, _ in dims)
    den = sum(w for _, _, w, _ in dims) or 1.0
    s = 100.0 * _th(1.8 * (num / den))

    # 绝对收益约束：相对基准再好，只要还在亏钱，就不能算「良好」
    ann = m.get("ann_ret", 0) or 0
    penalty = 1.0
    if ann < 0:
        penalty = max(0.25, 1.0 + ann / 10.0)
        s *= penalty

    def tag(v):
        if v > 0.45:
            return "优秀"
        if v > 0.15:
            return "良好"
        if v >= -0.15:
            return "一般"
        if v > -0.45:
            return "偏弱"
        return "较差"

    out = []
    for name, v, w, ev in dims:
        out.append({
            "name": name, "score": round(v, 4), "score100": round(v * 100, 1),
            "weight": w, "tag": tag(v),
            "side": "bull" if v > 0.15 else ("bear" if v < -0.15 else "neutral"),
            "evidence": [e for e in ev if e],
        })

    if s >= 55:
        lv = {"name": "优秀", "key": "strong", "color": "#e01b1b"}
    elif s >= 20:
        lv = {"name": "良好", "key": "good", "color": "#ef4b4b"}
    elif s > -20:
        lv = {"name": "一般", "key": "normal", "color": "#8a8a8a"}
    elif s > -55:
        lv = {"name": "偏弱", "key": "weak", "color": "#1ba784"}
    else:
        lv = {"name": "较差", "key": "bad", "color": "#0d8a6a"}

    return {
        "score": round(s, 1), "level": lv,
        "confidence": 70.0, "agreement": 65.0,
        "weighted": round(num / den, 4),
        "dimensions": out,
        "bull_dims": sum(1 for d in out if d["side"] == "bull"),
        "bear_dims": sum(1 for d in out if d["side"] == "bear"),
        "mode": "passive" if meta["passive"] else "active",
    }


def style_judge(meta, m):
    """风格判断：这只基金到底有多「主动」"""
    if not m:
        return None
    corr = m.get("corr")
    beta = m.get("beta")
    te = m.get("tracking_error")
    if corr is None:
        return {"text": "缺少基准数据，无法判断风格", "level": "unknown"}
    if corr > 0.95 and (te or 0) < 2.5:
        text = "高度跟踪基准（相关系数 %.2f，跟踪误差 %.2f%%），本质是指数化产品" % (corr, te or 0)
        level = "passive"
    elif corr > 0.85:
        text = "较强跟踪（相关系数 %.2f），在基准基础上做有限偏离" % corr
        level = "semi"
    elif corr > 0.6:
        text = "部分跟踪（相关系数 %.2f），有一定主动偏离" % corr
        level = "mixed"
    else:
        text = "与基准相关性仅 %.2f，主动偏离明显，属于真正的主动管理" % corr
        level = "active"
    if meta["passive"] and level == "active":
        text += "；但产品定位为被动，实际偏离偏大，需关注跟踪误差"
    if meta["active"] and level in ("passive", "semi"):
        text += "；名义上是主动管理，实际与基准高度相关，注意「伪主动」与风格漂移"
    return {"text": text, "level": level}
