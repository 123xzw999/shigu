# -*- coding: utf-8 -*-
"""
交易很轻松 · 终端分析
=====================
用法：
    python cli.py 600519
    python cli.py 600519 000001 510300
    python cli.py 茅台            # 支持名称

输出一份纯文本分析报告，可直接在控制台看。
"""

import os
import sys
import ctypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config

config.enable_utf8_console()


def _enable_vt():
    try:
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        k.GetConsoleMode(h, ctypes.byref(mode))
        k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


_enable_vt()

from core import engine, sina      # noqa: E402

R = "\033[91m"
G = "\033[92m"
Y = "\033[93m"
B = "\033[94m"
C = "\033[96m"
W = "\033[97m"
DIM = "\033[90m"
BOLD = "\033[1m"
E = "\033[0m"

WIDTH = 74


def color(v):
    return R if v > 0 else (G if v < 0 else DIM)


def hr(ch="─"):
    return DIM + ch * WIDTH + E


def title(text):
    pad = max(0, WIDTH - len(text) - 4)
    left = pad // 2
    right = pad - left
    return DIM + "┌" + "─" * (left + 2) + E + BOLD + W + " " + text + " " + E + DIM + \
        "─" * (right + 2) + "┐" + E


def bar(v, width=22):
    """-1..1 -> 可视化条"""
    n = int(abs(v) * width)
    n = max(1, n) if abs(v) > 0.02 else 0
    if v >= 0:
        return R + "█" * n + DIM + "·" * (width - n) + E
    return DIM + "·" * (width - n) + E + G + "█" * n + E


def fmt(v, d=2):
    if v is None:
        return "—"
    return ("%+." + str(d) + "f") % v


def report(code):
    d = engine.analyze(code)
    if not d.get("ok"):
        print(Y + "  ✗ %s：%s" % (code, d.get("reason", "分析失败")) + E)
        return

    q = d["quote"]
    a = d["analysis"]
    sc = a["score"]
    cp = a["chip"]
    ch = a["chan"]
    ph = a["phase"]
    lv = a["levels"]
    ad = a["advice"]
    sm = a["summary"]

    print()
    print(title("%s  %s" % (d["name"], d["symbol"].upper())))
    # 行情
    pct = q.get("change_pct", 0)
    pc = R if pct > 0 else (G if pct < 0 else DIM)
    price_txt = ("%.3f" % q.get("price", 0)) if q.get("price", 0) < 10 else ("%.2f" % q.get("price", 0))
    market_txt = d["market"] + " · " + {"stock": "股票", "fund": "基金/ETF",
                                        "ofund": "场外基金", "index": "指数"}.get(d["kind"], "")
    print("  " + BOLD + W + price_txt + E + "  " + pc + fmt(q.get("change", 0)) + E +
          "   " + pc + fmt(pct) + "%" + E + "   " + DIM + market_txt + E)
    print("  " + DIM + "今开 %s  昨收 %s  最高 %s  最低 %s  成交额 %s" % (
        ("%.2f" % q.get("open", 0)), ("%.2f" % q.get("prev_close", 0)),
        ("%.2f" % q.get("high", 0)), ("%.2f" % q.get("low", 0)),
        ("%.2f亿" % (q.get("amount", 0) / 1e8) if q.get("amount") else "—")) + E)

    # 评分
    print(hr())
    lvc = R if sc["score"] > 14 else (G if sc["score"] < -14 else DIM)
    print("  %s综合评分%s  %s%s%s  %s%s%s   置信度 %s%.0f%%%s   一致性 %s%.0f%%%s" % (
        BOLD, E,
        lvc + BOLD, fmt(sc["score"], 1), E,
        lvc, sc["level"]["name"], E,
        W, sc["confidence"], E,
        W, sc["agreement"], E))
    print()
    for dm in sc["dimensions"]:
        v = dm["score"]
        col = color(v)
        print("   %s%-4s%s %s %s%s%s  %s%s%s" % (
            DIM, dm["name"], E, bar(v),
            col, ("%+.0f" % dm["score100"]).rjust(4), E,
            DIM, dm["tag"], E))
    print()

    # 缠论
    if ch and ch.get("ok"):
        print(hr())
        tc = R if "上涨" in (ch["trend"] or "") else (G if "下跌" in (ch["trend"] or "") else DIM)
        print("  %s缠论结构%s  %s%s%s  ·  %s  ·  笔%d/线段%d/中枢%d" % (
            BOLD, E, tc, ch["trend"], E, ch["position"],
            ch["bi_count"], ch["duan_count"], ch["zs_count"]))
        if ch.get("cur_zs"):
            z = ch["cur_zs"]
            print("   %s当前中枢%s [%.2f, %.2f]  高度 %.1f%%" % (
                DIM, E, z["zd"], z["zg"], z["height_pct"]))
        sigs = (ch.get("signals") or [])[-3:]
        if sigs:
            print("   %s最近买卖点%s" % (DIM, E))
            for s in sigs:
                c2 = R if s["side"] == "buy" else G
                print("     %s%-4s%s %s  %8.2f   %s" % (
                    c2, s["type"], E, s["day"], s["price"], DIM + s["desc"][:36] + E))
        else:
            print("   %s近期无买卖点信号%s" % (DIM, E))

    # 主力阶段
    print(hr())
    pc2 = R if ph["phase"] in ("拉升", "吸筹") else (G if ph["phase"] in ("下跌", "派发") else DIM)
    print("  %s主力阶段%s  %s%s%s  置信度 %.0f%%" % (
        BOLD, E, pc2 + BOLD, ph["phase"], E, ph["confidence"] * 100))
    print("   " + DIM + ph.get("desc", "") + E)
    det = ph.get("detail") or {}
    if det:
        parts = []
        for k, v in sorted(det.items(), key=lambda x: -x[1]):
            parts.append("%s%.0f%%" % (k, v * 100))
        print("   " + DIM + "  ".join(parts) + E)

    # 筹码
    if cp and cp.get("ok"):
        print(hr())
        print("  %s筹码分布%s   %s主力成本%s %s%.2f%s   %s散户成本%s %s%.2f%s   %s控盘%s %.1f%%" % (
            BOLD, E,
            Y, E, W, cp["main_cost"], E,
            B, E, W, cp["retail_cost"], E,
            DIM, E, cp["control"]))
        print("   %s获利盘%.1f%%  套牢盘%.1f%%  集中度%.1f  成本分离%.2f%%%s" % (
            DIM, cp["profit_ratio"], cp["trapped_ratio"],
            cp["concentration"] * 100, cp["separation"], E))
        if cp.get("main_zone"):
            z = cp["main_zone"]
            print("   %s● 主力筹码集中区%s  %s%.2f ~ %.2f%s   (峰值 %.2f，距现价 %s%%)" % (
                Y, E, W + BOLD, z["low"], z["high"], E, z["peak"],
                fmt((z["peak"] / cp["price"] - 1) * 100)))
        if cp.get("retail_zone"):
            z = cp["retail_zone"]
            print("   %s● 散户筹码集中区%s  %s%.2f ~ %.2f%s   (峰值 %.2f，距现价 %s%%)" % (
                B, E, W + BOLD, z["low"], z["high"], E, z["peak"],
                fmt((z["peak"] / cp["price"] - 1) * 100)))
        vp = cp.get("vp")
        if vp:
            print("   %s◇ POC 成交峰 %s%.2f%s   价值区(70%%) %s%.2f ~ %.2f%s" % (
                DIM, W, vp["poc"], E, W, vp["val"], vp["vah"], E))

    # 各阶段成本
    segs = a.get("segments") or []
    if segs:
        print(hr())
        print("  %s各阶段主力成本（成交量加权）%s" % (BOLD, E))
        for s in segs[-5:]:
            c3 = R if s["phase"] in ("拉升", "吸筹") else (G if s["phase"] in ("下跌", "派发") else DIM)
            print("   %s%-4s%s %s ~ %s  %2d日  成本 %s%.2f%s  涨跌 %s%s%%%s" % (
                c3, s["phase"], E, s["start_day"][2:], s["end_day"][2:], s["days"],
                W, s["vwap"], E, color(s["chg_pct"]), fmt(s["chg_pct"], 1), E))

    # 形态
    pats = a.get("patterns") or {}
    if pats.get("list"):
        print(hr())
        print("  %sK线形态%s  %s%s%s" % (BOLD, E, DIM, pats.get("text", ""), E))
        for p in pats["list"][-4:]:
            c4 = R if p["side"] == "bull" else (G if p["side"] == "bear" else DIM)
            print("   %s%-8s%s %s  %s" % (c4, p["name"], E, p["day"],
                                          DIM + p["desc"][:44] + E))

    # 转折点判断
    tr = a.get("turning") or {}
    if tr.get("ok"):
        m = tr.get("meta") or {}
        stt = tr.get("state") or {}
        rev = tr.get("rev") or {}
        print(hr())
        print("  %s转折点判断%s  %s%s%s  %s%s%s" % (
            BOLD, E, W, m.get("sector", "—"), E,
            DIM, (m.get("how", "") + ("（兜底参数）" if m.get("fallback") else "")), E))
        stn = stt.get("name", "—")
        stc = R if "涨" in stn else (G if "跌" in stn else DIM)
        print("   %s当前状态%s %s%s%s   状态分 %s%+.2f%s   ADX %.0f   ATR %.2f%%   RSI %.0f" % (
            DIM, E, stc + BOLD, stn, E, color(stt.get("score", 0)),
            stt.get("score", 0), E, stt.get("adx", 0), stt.get("atr_pct", 0),
            stt.get("rsi", 0)))

        def _pbar(pv, width=22):
            k = int(round(max(0.0, min(1.0, pv)) * width))
            return "█" * k + "░" * (width - k)

        for key, label, cc in (("up", "底部反转", R), ("down", "顶部反转", G)):
            r = rev.get(key)
            if not r:
                continue
            pv = r.get("p", 0)
            pct = r.get("pct")
            flag = ("  " + BOLD + cc + "◆触发" + E) if r.get("sig") else ""
            hot = ("  " + cc + "分位 %d%%" % (pct * 100) + E) if pct is not None else "  " + DIM + "分位 —" + E
            print("   %s%s%s %s%s%s %s%.3f%s %s%s" % (
                DIM, label, E, cc, _pbar(pv), E, cc, pv, E, hot, flag))

        php = tr.get("phase")
        if php:
            pc2 = R if php.get("type") == "up" else G
            print("   %s当前段%s   %s%s %d 根%s   %s 起   累计 %s%+.1f%%%s" % (
                DIM, E, pc2, "上涨" if php.get("type") == "up" else "下跌",
                php.get("bars", 0), E, php.get("start_day", ""),
                color(php.get("chg", 0)), php.get("chg", 0), E))
        for e in (tr.get("evidence") or [])[:5]:
            print("   " + DIM + "· " + e + E)
        for nt in (tr.get("note") or [])[:2]:
            print("   " + Y + nt + E)

    # 关键价位 + 建议
    print(hr())
    sup = (lv.get("supports") or [{}])[0]
    res = (lv.get("resists") or [{}])[0]
    print("  %s支撑%s %s%.2f%s (%s)    %s压力%s %s%.2f%s (%s)    %s盈亏比%s %.2f" % (
        DIM, E, G, sup.get("price", 0), E, sup.get("label", ""),
        DIM, E, R, res.get("price", 0), E, res.get("label", ""),
        DIM, E, lv.get("risk_reward", 0)))
    print("  %s止损%s %.2f    %s目标%s %.2f" % (
        DIM, E, lv.get("stop", 0), DIM, E, lv.get("target", 0)))
    print()
    ac = R if ad["action"] in ("积极", "偏多") else (G if ad["action"] in ("看空", "回避") else Y)
    print("  %s▶ 操作建议：%s%s%s" % (ac, BOLD, ad["action"], E))
    print("  " + W + ad["advice"] + E)
    for n in (ad.get("notes") or [])[:5]:
        print("   " + DIM + "· " + n + E)

    # 阶段涨跌
    per = sm.get("periods") or {}
    items = []
    for k, v in per.items():
        if v is not None:
            items.append("%s %s%s%%%s" % (k, color(v), fmt(v, 2), E))
    if items:
        print(hr())
        print("  " + "   ".join(items))
    print(hr())
    print("  " + DIM + "数据：新浪财经 · 生成于 " + d["updated"] + E)
    print()


def main():
    args = sys.argv[1:]
    if not args:
        print()
        print("  交易很轻松 · 终端分析")
        print("  " + "─" * 60)
        print("  用法：python cli.py <代码或名称> [更多代码...]")
        print("  示例：python cli.py 600519")
        print("        python cli.py 600519 000001 510300")
        print("        python cli.py 茅台")
        print()
        try:
            v = input("  请输入代码/名称（直接回车退出）：").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not v:
            return
        args = [v]

    for raw in args:
        code = sina.resolve(raw)
        if not code:
            print(Y + "  ✗ 无法识别：%s（试试 6 位代码，如 600519）" % raw + E)
            continue
        try:
            report(code)
        except Exception as e:                       # noqa: BLE001
            print(R + "  ✗ %s 分析失败：%s" % (raw, e) + E)


if __name__ == "__main__":
    main()
