# -*- coding: utf-8 -*-
"""
缠论分析引擎 · chan.py
======================
实现链条：K线包含处理 → 分型 → 笔 → 线段 → 中枢 → 背驰 → 买卖点。

算法约定（与缠中说禅原文口径对齐）：
  1. 包含关系按「前一根合并K线相对更前一根」的方向处理：
     向上取高高、向下取低低。
  2. 分型：合并后连续三根，中间的最高/最低且两端不越界。
  3. 笔（老笔标准）：顶底分型交替，两分型之间合并K线索引差 >= CHAN_MIN_GAP(4)，
     且顶分型高点必须高于底分型低点。
  4. 线段：特征序列分型法。向上线段的特征序列由向下笔构成，
     出现顶分型即线段终结；向下线段反之。
  5. 中枢：连续三笔的价格区间有公共重叠，ZG = min(三笔高点)，ZD = max(三笔低点)。
     后续笔只要与 [ZD, ZG] 仍有重叠，中枢延续。
  6. 背驰：同向相邻两段，价格创新高/新低但 MACD 柱面积显著萎缩
     （前段面积 / 后段面积 > CHAN_DIVERGENCE_RATIO）。
  7. 买卖点：
     一买 = 下跌趋势末段背驰 + 底分型确认；一卖对称。
     二买 = 一买后首次回调不破一买低点；二卖对称。
     三买 = 向上离开中枢后回抽不回中枢（低点 > ZG）；三卖对称。
"""

from . import config


# ============================================================ 1. 包含处理

def merge_inclusive(bars):
    """K线包含关系合并。返回合并K线列表，每根记录映射到的原始下标范围。"""
    merged = []
    for i, b in enumerate(bars):
        h, l = b["high"], b["low"]
        if len(merged) < 2:
            merged.append({"high": h, "low": l, "start": i, "end": i})
            continue
        last, prev = merged[-1], merged[-2]
        direction = 1 if last["high"] > prev["high"] else -1
        contained = (h <= last["high"] and l >= last["low"]) or \
                    (h >= last["high"] and l <= last["low"])
        if contained:
            if direction == 1:
                last["high"] = max(h, last["high"])
                last["low"] = max(l, last["low"])
            else:
                last["high"] = min(h, last["high"])
                last["low"] = min(l, last["low"])
            last["end"] = i
        else:
            merged.append({"high": h, "low": l, "start": i, "end": i})
    return merged


# ============================================================ 2. 分型

def find_fractals(merged):
    fs = []
    for i in range(1, len(merged) - 1):
        a, b, c = merged[i - 1], merged[i], merged[i + 1]
        if b["high"] > a["high"] and b["high"] > c["high"] and \
           b["low"] > a["low"] and b["low"] > c["low"]:
            fs.append({"type": "top", "mi": i, "price": b["high"], "bi": b["end"]})
        elif b["low"] < a["low"] and b["low"] < c["low"] and \
                b["high"] < a["high"] and b["high"] < c["high"]:
            fs.append({"type": "bottom", "mi": i, "price": b["low"], "bi": b["end"]})
    return fs


# ============================================================ 3. 笔

def build_bi(fractals, min_gap=None):
    min_gap = min_gap or config.CHAN_MIN_GAP
    bis = []
    cur = None
    for f in fractals:
        if cur is None:
            cur = f
            continue
        if f["type"] == cur["type"]:
            # 同类取更极端
            if (f["type"] == "top" and f["price"] > cur["price"]) or \
               (f["type"] == "bottom" and f["price"] < cur["price"]):
                cur = f
            continue
        if f["mi"] - cur["mi"] < min_gap:
            continue
        # 顶必须高于底
        if cur["type"] == "bottom" and f["price"] <= cur["price"]:
            cur = f
            continue
        if cur["type"] == "top" and f["price"] >= cur["price"]:
            cur = f
            continue
        bis.append({
            "start": cur, "end": f,
            "direction": 1 if f["type"] == "top" else -1,
            "start_price": cur["price"], "end_price": f["price"],
            "start_bar": cur["bi"], "end_bar": f["bi"],
            "high": max(cur["price"], f["price"]),
            "low": min(cur["price"], f["price"]),
            "amplitude": abs(f["price"] - cur["price"]) / cur["price"] * 100 if cur["price"] else 0,
        })
        cur = f
    return bis


# ============================================================ 4. 线段

def build_duan(bis):
    """
    特征序列法简化实现。
    向上线段：特征序列 = 其中的向下笔（取其 high/low）。
    当特征序列出现顶分型（后一元素高点、低点双双走低），线段终结。
    """
    n = len(bis)
    if n < 3:
        return []
    duans = []
    s = 0
    while s <= n - 3:
        d = bis[s]["direction"]
        end = None
        # 特征序列：与线段反向的笔
        feat = []
        for k in range(s, n):
            if bis[k]["direction"] == -d:
                feat.append({"k": k, "high": bis[k]["start_price"] if d == 1 else bis[k]["end_price"],
                             "low": bis[k]["end_price"] if d == 1 else bis[k]["start_price"]})
                if len(feat) >= 3:
                    a, b, c = feat[-3], feat[-2], feat[-1]
                    if d == 1:
                        # 顶分型：中间最高
                        if b["high"] > a["high"] and b["high"] > c["high"]:
                            end = b["k"] - 1
                            break
                    else:
                        if b["low"] < a["low"] and b["low"] < c["low"]:
                            end = b["k"] - 1
                            break
        if end is None or end <= s:
            end = n - 1
        end = min(end, n - 1)
        if end - s < 2:
            end = min(s + 2, n - 1)
        duans.append({
            "start_bi": s, "end_bi": end, "direction": d,
            "start_price": bis[s]["start_price"], "end_price": bis[end]["end_price"],
            "start_bar": bis[s]["start_bar"], "end_bar": bis[end]["end_bar"],
            "high": max(bis[k]["high"] for k in range(s, end + 1)),
            "low": min(bis[k]["low"] for k in range(s, end + 1)),
        })
        s = end
        if s >= n - 2:
            break
    return duans


# ============================================================ 5. 中枢

def build_zhongshu(bis, level="bi"):
    zs_list = []
    n = len(bis)
    i = 0
    while i + 2 < n:
        r = [(b["low"], b["high"]) for b in bis[i:i + 3]]
        zg = min(x[1] for x in r)
        zd = max(x[0] for x in r)
        if zg > zd:
            j = i + 3
            while j < n:
                if bis[j]["low"] < zg and bis[j]["high"] > zd:   # 仍与中枢重叠
                    j += 1
                else:
                    break
            zs_list.append({
                "level": level,
                "start_bi": i, "end_bi": j - 1,
                "zd": zd, "zg": zg,
                "mid": (zd + zg) / 2,
                "height": zg - zd,
                "height_pct": (zg - zd) / zd * 100 if zd else 0,
                "start_bar": bis[i]["start_bar"],
                "end_bar": bis[j - 1]["end_bar"],
                "bi_count": j - i,
            })
            i = j
        else:
            i += 1
    return zs_list


# ============================================================ 6. 背驰

def _macd_area(hist, i1, i2):
    seg = [abs(x) for x in hist[i1:i2 + 1] if x is not None]
    return sum(seg)


def find_divergence(bis, hist, ratio=None):
    """
    背驰：比较「隔一笔」的两个同向笔（中间夹一个反向笔），
    价格创新高/新低但 MACD 柱面积萎缩。
    """
    ratio = ratio or config.CHAN_DIVERGENCE_RATIO
    out = []
    for i in range(2, len(bis)):
        prev, b = bis[i - 2], bis[i]
        if prev["direction"] != b["direction"]:
            continue
        a1 = _macd_area(hist, prev["start_bar"], prev["end_bar"])
        a2 = _macd_area(hist, b["start_bar"], b["end_bar"])
        p1 = abs(prev["end_price"] - prev["start_price"])
        p2 = abs(b["end_price"] - b["start_price"])
        if a2 <= 0 or a1 <= 0 or p1 <= 0:
            continue
        shrink = a1 / a2
        if b["direction"] == 1:
            new_extreme = b["end_price"] > prev["end_price"]
            kind = "顶背驰"
        else:
            new_extreme = b["end_price"] < prev["end_price"]
            kind = "底背驰"
        if new_extreme and shrink >= ratio and p2 >= p1 * 0.45:
            out.append({
                "kind": kind, "bi_index": i, "bar": b["end_bar"],
                "price": b["end_price"], "area_prev": round(a1, 2),
                "area_now": round(a2, 2), "shrink": round(shrink, 2),
                "day": "",
            })
    return out


# ============================================================ 7. 买卖点

def find_signals(bis, zs_list, divergences):
    sigs = []
    div_by_bi = {d["bi_index"]: d for d in divergences}

    # --- 一买 / 一卖：背驰 + 笔终结
    for d in divergences:
        if d["kind"] == "底背驰":
            sigs.append({"type": "一买", "side": "buy", "bar": d["bar"],
                         "price": d["price"], "strength": 0.85,
                         "desc": "下跌段 MACD 面积萎缩 %.1f 倍，底背驰成立" % d["shrink"]})
        else:
            sigs.append({"type": "一卖", "side": "sell", "bar": d["bar"],
                         "price": d["price"], "strength": 0.85,
                         "desc": "上涨段 MACD 面积萎缩 %.1f 倍，顶背驰成立" % d["shrink"]})

    # --- 二买 / 二卖：一买后的首次回调
    for k, s in enumerate(list(sigs)):
        if s["type"] != "一买":
            continue
        idx = s["bar"]
        after = [b for b in bis if b["start_bar"] > idx]
        if len(after) >= 2 and after[0]["direction"] == 1:
            pull = after[1] if after[1]["direction"] == -1 else None
            if pull and pull["end_price"] > s["price"] * 0.995:
                sigs.append({"type": "二买", "side": "buy", "bar": pull["end_bar"],
                             "price": pull["end_price"], "strength": 0.72,
                             "desc": "一买后回调不破前低，二买成立"})
    for s in list(sigs):
        if s["type"] != "一卖":
            continue
        idx = s["bar"]
        after = [b for b in bis if b["start_bar"] > idx]
        if len(after) >= 2 and after[0]["direction"] == -1:
            pull = after[1] if after[1]["direction"] == 1 else None
            if pull and pull["end_price"] < s["price"] * 1.005:
                sigs.append({"type": "二卖", "side": "sell", "bar": pull["end_bar"],
                             "price": pull["end_price"], "strength": 0.72,
                             "desc": "一卖后反弹不过前高，二卖成立"})

    # --- 三买 / 三卖：离开中枢后回抽不回中枢
    for zs in zs_list:
        j = zs["end_bi"] + 1
        if j >= len(bis):
            continue
        # 向上离开
        if bis[j]["high"] > zs["zg"] and bis[j]["direction"] == 1:
            if j + 1 < len(bis) and bis[j + 1]["direction"] == -1:
                pull = bis[j + 1]
                if pull["end_price"] > zs["zg"]:
                    sigs.append({"type": "三买", "side": "buy", "bar": pull["end_bar"],
                                 "price": pull["end_price"], "strength": 0.78,
                                 "desc": "回抽不回中枢（低点 %.2f > ZG %.2f）" % (pull["end_price"], zs["zg"])})
        if bis[j]["low"] < zs["zd"] and bis[j]["direction"] == -1:
            if j + 1 < len(bis) and bis[j + 1]["direction"] == 1:
                pull = bis[j + 1]
                if pull["end_price"] < zs["zd"]:
                    sigs.append({"type": "三卖", "side": "sell", "bar": pull["end_bar"],
                                 "price": pull["end_price"], "strength": 0.78,
                                 "desc": "反抽不回中枢（高点 %.2f < ZD %.2f）" % (pull["end_price"], zs["zd"])})

    sigs.sort(key=lambda x: x["bar"])
    # 去重：同一根K线同一类型只保留一个
    seen = set()
    uniq = []
    for s in sigs:
        key = (s["type"], s["bar"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    return uniq


# ============================================================ 主入口

def analyze(bars, macd_hist=None):
    if not bars or len(bars) < 30:
        return {"ok": False, "reason": "K线不足 30 根，无法进行缠论分析"}

    merged = merge_inclusive(bars)
    fractals = find_fractals(merged)
    bis = build_bi(fractals)
    duans = build_duan(bis)
    zs_list = build_zhongshu(bis)
    hist = macd_hist if macd_hist else [0] * len(bars)
    divs = find_divergence(bis, hist)
    sigs = find_signals(bis, zs_list, divs)

    last = bars[-1]["close"]
    cur_bi = bis[-1] if bis else None
    cur_zs = zs_list[-1] if zs_list else None

    pos = "无中枢"
    zs_age = None
    zs_dist = None
    if cur_zs:
        if last > cur_zs["zg"]:
            pos = "中枢上方"
        elif last < cur_zs["zd"]:
            pos = "中枢下方"
        else:
            pos = "中枢内部"
        zs_age = len(bars) - 1 - cur_zs["end_bar"]
        zs_dist = round((last - cur_zs["mid"]) / cur_zs["mid"] * 100, 2) if cur_zs["mid"] else 0.0
        if zs_age > 60:
            pos = pos + "（中枢已形成 %d 根K线前，当前为离开段）" % zs_age

    # 走势类型
    trend = "盘整"
    if len(zs_list) >= 2:
        z1, z2 = zs_list[-2], zs_list[-1]
        if z2["mid"] > z1["mid"] * 1.005 and z2["zd"] > z1["zg"]:
            trend = "上涨趋势"
        elif z2["mid"] < z1["mid"] * 0.995 and z2["zg"] < z1["zd"]:
            trend = "下跌趋势"
        elif z2["mid"] > z1["mid"]:
            trend = "震荡上行"
        elif z2["mid"] < z1["mid"]:
            trend = "震荡下行"
    elif len(zs_list) == 1:
        trend = "盘整"

    # 最近信号
    recent = [s for s in sigs if s["bar"] >= len(bars) - 60]
    last_sig = sigs[-1] if sigs else None
    for s in sigs:
        s["day"] = bars[s["bar"]]["day"] if 0 <= s["bar"] < len(bars) else ""
    for d in divs:
        d["day"] = bars[d["bar"]]["day"] if 0 <= d["bar"] < len(bars) else ""

    return {
        "ok": True,
        "merged_count": len(merged),
        "fractal_count": len(fractals),
        "bi_count": len(bis),
        "duan_count": len(duans),
        "zs_count": len(zs_list),
        "fractals": fractals[-40:],
        "bis": bis,
        "duans": duans,
        "zhongshu": zs_list,
        "divergences": divs,
        "signals": sigs,
        "recent_signals": recent[-6:],
        "last_signal": last_sig,
        "trend": trend,
        "position": pos,
        "zs_age": zs_age,
        "zs_dist": zs_dist,
        "cur_bi": cur_bi,
        "cur_zs": cur_zs,
        "price": last,
        "nearest_support": cur_zs["zd"] if cur_zs and last > cur_zs["zd"] else None,
        "nearest_resist": cur_zs["zg"] if cur_zs and last < cur_zs["zg"] else None,
    }
