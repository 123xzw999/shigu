# -*- coding: utf-8 -*-
"""
转折点识别 · turning.py
=======================
判断「趋势有没有走到转折点」—— 把 交易量化函数 项目标定好的逐板块模型
搬到本系统里，用纯标准库重写推理链路（不引入 numpy / pandas）。

方法（与标定端完全一致，任何一处不一致都会让概率失真）
------------------------------------------------------
1. 拐点标注：Pagan-Sossounov 删失局部极值（Bry-Boschan 风格）
   —— 候选局部极值 → 强制峰谷交替 → 删掉「太短」或「太小」的阶段 → 迭代到稳定
2. 特征：44 维（趋势 / 位置 / 动量 / 量能 / 波动 / 结构 / 背离 / 力度 + 周K共振）
3. 模型：逐板块 L2 逻辑回归（权重从 data/turning_profiles.json 加载）
4. 输出：反转概率 + 该概率在过去 250 根里的分位 + 触发与否 + 可解释依据

⚠ 绝对阈值不可跨时段迁移（标定时选的阈值，过一段时间概率分布就漂了），
  所以这里**同时给分位**。看分位比看阈值靠谱，这是标定阶段实测出来的结论。
"""

import json
import math
import os

from . import indicators as ta

_HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(os.path.dirname(_HERE), "data", "turning_profiles.json")
SECTOR_MAP_PATH = os.path.join(os.path.dirname(_HERE), "data", "sector_map.json")

_PROF = None
_SMAP = None
EPS = 1e-9

# 概率分位的观察窗口（根）
RANK_WIN = 160
# 分位触发线：0.95 = 近一年最像反转的 5% 时刻
RANK_THR = 0.95

# 分析基准周期 → 用哪套模型
SCALE_KIND = {240: "day", 1200: "week"}


# ============================================================ 板块映射
#
# 顺序即优先级：越具体的放前面。
# 「半导体」必须排在「电子」之前，「白酒」必须排在「食品」之前，
# 否则细分类会被粗分类吃掉。
SECTOR_RULES = [
    ("new_ljhy", ["白酒", "酿酒", "啤酒", "黄酒", "葡萄酒", "酒类"]),
    ("new_swzz", ["医药", "生物制品", "生物医药", "制药", "疫苗", "中药", "化学制药",
                  "原料药", "医疗器械", "医疗服务", "CXO", "CRO", "创新药", "血液制品",
                  "体外诊断", "医美"]),
    ("new_dzqj", ["半导体", "芯片", "集成电路", "电子元件", "光学光电子", "面板",
                  "消费电子", "被动元件", "分立器件", "印制电路", "PCB", "存储",
                  "封测", "光刻", "电子化学品"]),
    ("new_dzxx", ["软件", "计算机", "通信", "互联网", "IT服务", "信息安全", "云计算",
                  "信息技术", "电信", "游戏", "数据中心", "人工智能"]),
    ("new_jrhy", ["银行", "证券", "保险", "信托", "多元金融", "券商", "金融服务",
                  "非银金融"]),
    ("new_fdc", ["房地产", "地产", "置业", "园区开发", "房屋建设"]),
    ("new_mthy", ["煤炭", "焦煤", "动力煤", "焦炭"]),
    ("new_ysjs", ["有色", "黄金", "铜", "铝", "锂", "稀土", "钴", "镍", "小金属",
                  "金属新材料", "贵金属"]),
    ("new_gthy", ["钢铁", "特钢", "普钢", "冶钢"]),
    ("new_dlhy", ["电力", "水电", "火电", "核电", "电网", "燃气", "公用事业",
                  "热力", "环保"]),
    ("new_jxhy", ["机械", "工程机械", "机床", "机器人", "专用设备", "通用设备",
                  "自动化设备", "仪器仪表", "轨交", "船舶", "航空装备", "军工",
                  "航天", "兵器"]),
    ("new_qczz", ["汽车", "整车", "汽车零部件", "乘用车", "商用车", "新能源车",
                  "摩托车"]),
    ("new_nlmy", ["农业", "养殖", "种植", "饲料", "渔业", "林业", "农产品",
                  "畜牧", "动物保健"]),
    ("new_cmyl", ["传媒", "影视", "院线", "出版", "广告", "文化", "教育"]),
    ("new_jdhy", ["家电", "白色家电", "小家电", "厨卫", "黑色家电", "家居用品"]),
    ("new_sphy", ["食品", "饮料", "乳品", "调味", "零食", "烘焙", "预制菜",
                  "食品加工"]),
]


def _load():
    global _PROF
    if _PROF is None:
        try:
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                _PROF = json.load(f)
        except Exception:                                  # noqa: BLE001
            _PROF = {"features": [], "sectors": {}, "fallback": {}}
    return _PROF


def _load_map():
    global _SMAP
    if _SMAP is None:
        try:
            with open(SECTOR_MAP_PATH, "r", encoding="utf-8") as f:
                _SMAP = json.load(f)
        except Exception:                                  # noqa: BLE001
            _SMAP = {"map": {}, "names": {}}
    return _SMAP


def available():
    p = _load()
    return bool(p.get("sectors"))


def match_sector(name="", sector_name="", industry="", symbol=""):
    """
    把标的映射到 15 个已标定板块之一，三级优先：
      1. 代码查表（data/sector_map.json，1038 只 A 股权重股，最准）
      2. 名称 / 行业关键词
      3. 兜底（调用方按资金属性用平均参数）
    返回 (node, how)。
    """
    prof = _load()
    smap = _load_map()
    if symbol:
        code = str(symbol).strip().lower()
        node = (smap.get("map") or {}).get(code)
        if not node:
            # 兼容不带前缀的写法
            for pre in ("sh", "sz", "bj"):
                node = (smap.get("map") or {}).get(pre + code) if not code.startswith(pre) else None
                if node:
                    break
        if node and node in prof.get("sectors", {}):
            nm = (smap.get("names") or {}).get(code, "")
            return node, "代码查表命中%s" % ("（%s）" % nm if nm else "")

    text = " ".join(x for x in (name, sector_name, industry) if x)
    if not text:
        return None, "无名称信息"
    for node, keys in SECTOR_RULES:
        if node not in prof.get("sectors", {}):
            continue
        for k in keys:
            if k and k in text:
                return node, "名称命中「%s」" % k
    return None, "未匹配到已标定板块"


# ============================================================ 工具
def _f(v, d=0.0):
    return v if (v is not None and v == v) else d


def _ok(v):
    return v is not None and v == v


def _pct_change(a, b):
    return (a / b - 1.0) if b else 0.0


def _rank_pct(seq, v):
    """v 在 seq 里的百分位（平均排名法，与 pandas rank(pct=True) 一致）"""
    n = len(seq)
    if n == 0:
        return 0.5
    less = sum(1 for x in seq if x < v)
    eq = sum(1 for x in seq if x == v)
    return (less + (eq + 1) / 2.0) / n


def _slope_t(vals, n):
    """对数序列线性回归斜率的 t 统计量（可跨标的比较）"""
    if len(vals) < n:
        return 0.0
    seg = [math.log(v) if v > 0 else 0.0 for v in vals[-n:]]
    mx = (n - 1) / 2.0
    my = sum(seg) / n
    sxx = sum((i - mx) ** 2 for i in range(n))
    if not sxx:
        return 0.0
    b = sum((i - mx) * (y - my) for i, y in enumerate(seg)) / sxx
    a = my - b * mx
    sse = sum((y - (a + b * i)) ** 2 for i, y in enumerate(seg))
    se = math.sqrt(sse / max(n - 2, 1) / sxx)
    return b / (se + EPS)


def _divergence(price, ind, n):
    """价格与指标的方向背离度：>0 同向，<0 背离"""
    if len(price) < n + 1 or len(ind) < n + 1:
        return 0.0
    p0, p1 = price[-1 - n], price[-1]
    i0, i1 = ind[-1 - n], ind[-1]
    if not (_ok(p0) and _ok(i0)) or not p0 or not i0:
        return 0.0
    pz = _pct_change(p1, p0)
    seg = [abs(x) for x in ind[-n:] if _ok(x)]
    im = (sum(seg) / len(seg)) if seg else 0.0
    iz = (i1 - i0) / (im + EPS) if _ok(i1) else 0.0
    prod = pz * iz
    sgn = 1.0 if prod >= 0 else -1.0
    return -sgn * min(abs(prod), 5.0)


def _days_since(flags):
    """距上次条件成立多少根（未成立过 = None）"""
    out, last = [], None
    for i, ok in enumerate(flags):
        if ok:
            last = i
        out.append((i - last) if last is not None else None)
    return out


# ============================================================ 周K
def to_weekly(bars):
    """日K → 周K（自然周，按 ISO 周分组）。最后一根可能是未完成周，用 shift 语义规避。"""
    out = []
    cur_key = None
    cur = None
    for b in bars:
        d = str(b["day"])[:10]
        try:
            import datetime as _dt
            dt = _dt.date(int(d[0:4]), int(d[5:7]), int(d[8:10]))
            iso = dt.isocalendar()
            key = (iso[0], iso[1])
        except Exception:                                   # noqa: BLE001
            key = d[:7]
        if key != cur_key:
            if cur is not None:
                out.append(cur)
            cur_key = key
            cur = {"day": d, "open": b["open"], "high": b["high"],
                   "low": b["low"], "close": b["close"], "volume": b.get("volume", 0.0)}
        else:
            cur["day"] = d
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["volume"] = cur.get("volume", 0.0) + b.get("volume", 0.0)
    if cur is not None:
        out.append(cur)
    return out


# ============================================================ 特征
#
# ★ 性能要点：特征只需要「最后一根」的值，但 EMA / RMA(Wilder) 是递推的。
#   好在两者都有遗忘性 —— 从 300 根之前启动，初始值影响衰减到 1e-9 以下，
#   而计算量从 O(全部历史) 降到 O(300)。这让「逐根重算 250 根算概率分位」
#   从几十秒降到 0.1 秒。
TAIL = 500


def _rolling_extreme(vals, w, want_max=True):
    """窗口 [i-w+1, i] 的极值，单调队列 O(n)。与 pandas rolling().max() 一致。"""
    from collections import deque
    n = len(vals)
    out = [None] * n
    dq = deque()
    for i, v in enumerate(vals):
        while dq and ((vals[dq[-1]] <= v) if want_max else (vals[dq[-1]] >= v)):
            dq.pop()
        dq.append(i)
        if dq[0] <= i - w:
            dq.popleft()
        if i >= w - 1:
            out[i] = vals[dq[0]]
    return out


def _tail_ema(vals, span, tail=TAIL):
    seg = vals[-tail:]
    if not seg:
        return 0.0
    a = 2.0 / (span + 1.0)
    e = seg[0]
    for v in seg[1:]:
        e = a * v + (1 - a) * e
    return e


def _tail_rma(vals, n, tail=TAIL):
    seg = vals[-tail:]
    if not seg:
        return 0.0
    a = 1.0 / n
    e = seg[0]
    for v in seg[1:]:
        e = a * v + (1 - a) * e
    return e


def _tail_rsi(close, n=14, tail=TAIL):
    seg = close[-tail:]
    if len(seg) < n + 2:
        return 50.0
    a = 1.0 / n
    up = dn = 0.0
    for i in range(1, n + 1):
        d = seg[i] - seg[i - 1]
        up += max(d, 0.0)
        dn += max(-d, 0.0)
    au, ad = up / n, dn / n
    for i in range(n + 1, len(seg)):
        d = seg[i] - seg[i - 1]
        au = a * max(d, 0.0) + (1 - a) * au
        ad = a * max(-d, 0.0) + (1 - a) * ad
    return 100.0 - 100.0 / (1.0 + au / (ad + EPS))


def _tail_macd(close, fast=12, slow=26, signal=9, tail=TAIL, want="hist"):
    """返回最后一根的 DIF 或 MACD 柱。背离必须用 DIF，用柱会算出反向结果。"""
    seg = close[-tail:]
    if len(seg) < slow + signal:
        return 0.0
    af, asl, ag = 2.0 / (fast + 1), 2.0 / (slow + 1), 2.0 / (signal + 1)
    ef = es = seg[0]
    dif_series = []
    for v in seg[1:]:
        ef = af * v + (1 - af) * ef
        es = asl * v + (1 - asl) * es
        dif_series.append(ef - es)
    dea = dif_series[0]
    for v in dif_series[1:]:
        dea = ag * v + (1 - ag) * dea
    return dif_series[-1] if want == "dif" else (dif_series[-1] - dea)


def _tail_adx(high, low, close, n=14, tail=TAIL):
    seg_h, seg_l, seg_c = high[-tail:], low[-tail:], close[-tail:]
    m = len(seg_c)
    if m < n + 2:
        return 0.0
    tr, pdm, ndm = [], [], []
    for i in range(1, m):
        tr.append(max(seg_h[i] - seg_l[i], abs(seg_h[i] - seg_c[i - 1]),
                      abs(seg_l[i] - seg_c[i - 1])))
        up = seg_h[i] - seg_h[i - 1]
        dn = seg_l[i - 1] - seg_l[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        ndm.append(dn if (dn > up and dn > 0) else 0.0)
    a = 1.0 / n
    atr_ = tr[0]
    sp = pdm[0]
    sn = ndm[0]
    dxs = []
    for i in range(1, len(tr)):
        atr_ = a * tr[i] + (1 - a) * atr_
        sp = a * pdm[i] + (1 - a) * sp
        sn = a * ndm[i] + (1 - a) * sn
        pdi = 100.0 * sp / (atr_ + EPS)
        ndi = 100.0 * sn / (atr_ + EPS)
        dxs.append(100.0 * abs(pdi - ndi) / (pdi + ndi + EPS))
    if not dxs:
        return 0.0
    ax = dxs[0]
    for v in dxs[1:]:
        ax = a * v + (1 - a) * ax
    return ax


def _tail_atr(high, low, close, n=14, tail=TAIL):
    seg_h, seg_l, seg_c = high[-tail:], low[-tail:], close[-tail:]
    m = len(seg_c)
    if m < n + 2:
        return 0.0
    tr = [0.0]
    for i in range(1, m):
        tr.append(max(seg_h[i] - seg_l[i], abs(seg_h[i] - seg_c[i - 1]),
                      abs(seg_l[i] - seg_c[i - 1])))
    return _tail_rma(tr, n)


def _core_features(bars):
    """37 维日线特征（只算最后一根）"""
    n = len(bars)
    tail = bars[-TAIL:]
    close = [b["close"] for b in tail]
    high = [b["high"] for b in tail]
    low = [b["low"] for b in tail]
    open_ = [b["open"] for b in tail]
    vol = [b.get("volume", 0.0) or 0.0 for b in tail]
    c = close[-1]
    f = {}

    # ---- 趋势
    e5 = _tail_ema(close, 5)
    e10 = _tail_ema(close, 10)
    e20 = _tail_ema(close, 20)
    e60 = _tail_ema(close, 60)
    f["ema_bias5"] = _pct_change(c, e5)
    f["ema_bias20"] = _pct_change(c, e20)
    f["ema_bias60"] = _pct_change(c, e60)
    f["ema_align"] = ((1 if e5 > e10 else -1) + (1 if e10 > e20 else -1)
                      + (1 if e20 > e60 else -1)) / 3.0
    f["slope_t20"] = _slope_t(close, 20)
    f["adx14"] = _tail_adx(high, low, close, 14)

    # ---- 位置
    hi60, lo60 = max(high[-60:]), min(low[-60:])
    hi120, lo120 = max(high[-120:]), min(low[-120:])
    f["pos_60"] = (c - lo60) / (hi60 - lo60 + EPS)
    f["pos_120"] = (c - lo120) / (hi120 - lo120 + EPS)
    seg60 = close[-60:]
    m60 = sum(seg60) / 60.0
    sd60 = math.sqrt(sum((x - m60) ** 2 for x in seg60) / 59.0)
    f["zscore60"] = (c - m60) / (sd60 + EPS)
    hi250 = max(high[-250:]) if n >= 250 else max(high)
    lo250 = min(low[-250:]) if n >= 250 else min(low)
    f["dist_hi250"] = _pct_change(c, hi250)
    f["dist_lo250"] = _pct_change(c, lo250)

    # ---- 动量
    for k in (5, 10, 20, 60):
        f["roc%d" % k] = _pct_change(c, close[-1 - k]) if len(close) > k else 0.0
    f["rsi14"] = _tail_rsi(close, 14)
    f["macd_hist_n"] = (_tail_macd(close) / (c + EPS)) * 100.0

    # ---- 量能
    v20 = sum(vol[-20:]) / 20.0
    v60 = sum(vol[-60:]) / 60.0
    v250 = sum(vol[-250:]) / 250.0 if len(vol) >= 250 else sum(vol) / max(len(vol), 1)
    f["vr20"] = vol[-1] / (v20 + EPS)
    f["vr60"] = v20 / (v60 + EPS)
    obv_acc = 0.0
    obv_list = [0.0]
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv_acc += vol[i]
        elif close[i] < close[i - 1]:
            obv_acc -= vol[i]
        obv_list.append(obv_acc)
    f["obv_slope"] = ((obv_list[-1] - obv_list[-21]) / (sum(vol[-20:]) + EPS)) \
        if len(obv_list) > 21 else 0.0
    f["vol_trend"] = v60 / (v250 + EPS)
    f["pv_div"] = max(-f["roc20"], 0.0) * max(min(1.0 - f["vr60"], 1.0), -1.0)

    # ---- 波动
    atr_now = _tail_atr(high, low, close, 14)
    f["atr_pct"] = atr_now / (c + EPS)
    bw_series = []
    for i in range(20, len(close) + 1):
        seg = close[i - 20:i]
        m = sum(seg) / 20.0
        sd = math.sqrt(sum((x - m) ** 2 for x in seg) / 19.0)
        bw_series.append((4.0 * sd) / (m + EPS))
    f["bb_width"] = bw_series[-1] if bw_series else 0.0
    bw_win = bw_series[-120:] if len(bw_series) >= 120 else bw_series
    f["bb_width_q"] = _rank_pct(bw_win[:-1] or [0.0], bw_win[-1]) if bw_win else 0.5
    atrp = []
    for i in range(max(80, len(close) - 80), len(close) + 1):
        seg_h, seg_l, seg_c = high[i - 80:i], low[i - 80:i], close[i - 80:i]
        atrp.append(_tail_atr(seg_h, seg_l, seg_c, 14, tail=80) / (seg_c[-1] + EPS))
    if len(atrp) >= 60:
        w20, w60 = atrp[-20:], atrp[-60:]
        m60a = sum(w60) / 60.0
        m20a = sum(w20) / 20.0
        sd20 = math.sqrt(sum((x - m20a) ** 2 for x in w20) / 19.0)
        f["vol_of_vol"] = sd20 / (m60a + EPS)
    else:
        f["vol_of_vol"] = 1.0

    # ---- 结构：必须扫**全序列**。
    #      close >= 60 根 high 极值这种事极少发生，只看尾部会把 hh_days 截断成 TAIL，
    #      与标定端（全序列）差一个数量级 —— 这个特征权重不小，必须对齐。
    fh = [b["high"] for b in bars]
    fl = [b["low"] for b in bars]
    fc = [b["close"] for b in bars]
    rmax60 = _rolling_extreme(fh, 60, True)
    rmin60 = _rolling_extreme(fl, 60, False)
    hh = _days_since([rmax60[i] is not None and fc[i] >= rmax60[i] for i in range(len(fc))])
    ll = _days_since([rmin60[i] is not None and fc[i] <= rmin60[i] for i in range(len(fc))])
    f["hh_days"] = hh[-1] if hh[-1] is not None else float(len(fc))
    f["ll_days"] = ll[-1] if ll[-1] is not None else float(len(fc))
    rng = high[-1] - low[-1]
    f["body_ratio"] = abs(close[-1] - open_[-1]) / (rng + EPS)
    f["upper_shadow"] = (high[-1] - max(close[-1], open_[-1])) / (rng + EPS)
    f["lower_shadow"] = (min(close[-1], open_[-1]) - low[-1]) / (rng + EPS)

    # ---- 背离（只需最后 22 个指标点，之前算 300 个纯属浪费）
    rsi_series = []
    for i in range(max(21, len(close) - 21), len(close) + 1):
        rsi_series.append(_tail_rsi(close[i - 80:i] if i >= 80 else close[:i], 14))
    dif_series = []
    for i in range(max(21, len(close) - 21), len(close) + 1):
        dif_series.append(_tail_macd(close[i - 120:i] if i >= 120 else close[:i], want="dif"))
    f["rsi_div"] = _divergence(close, rsi_series, 20)
    f["macd_div"] = _divergence(close, dif_series, 20)
    f["price_vol_div"] = _divergence(close, obv_list[-len(close):], 20)

    # ---- 力度比（26 根内多空占比）
    up_s = dn_s = 0.0
    for i in range(max(1, len(close) - 26), len(close)):
        d = close[i] - close[i - 1]
        if d > 0:
            up_s += d
        else:
            dn_s += -d
    tot = up_s + dn_s + EPS
    f["ar26"] = up_s / tot
    f["ab_log"] = max(min(math.log((up_s + EPS) / (dn_s + EPS)), 4.0), -4.0)
    f["crp"] = (close[-1] - low[-1]) / (rng + EPS)
    return f


WEEKLY_KEYS = ["ema_align", "slope_t20", "pos_60", "rsi14", "adx14", "vr20", "roc10"]


def _weekly_features(weekly, upto_day):
    """
    取「最近一根已结束的周K」的特征，作为日K 的附加列。
    严格因果：本周要到周五收盘才成立，所以只取 day < 当前日K 的那根。
    """
    if not weekly or len(weekly) < 130:
        return {("w_" + k): 0.0 for k in WEEKLY_KEYS}
    usable = [w for w in weekly if str(w["day"])[:10] < str(upto_day)[:10]]
    if len(usable) < 130:
        return {("w_" + k): 0.0 for k in WEEKLY_KEYS}
    wf = _core_features(usable)
    return {("w_" + k): wf.get(k, 0.0) for k in WEEKLY_KEYS}


def build_features(bars, weekly=None):
    f = _core_features(bars)
    if weekly is not None:
        f.update(_weekly_features(weekly, bars[-1]["day"]))
    else:
        f.update({("w_" + k): 0.0 for k in WEEKLY_KEYS})
    return f


# ============================================================ 推理
def _sigmoid(z):
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _predict(feat, feats, model):
    """feat: dict, feats: 全局特征名表, model: {idx,w,mu,sd}"""
    z = model["w"][-1]
    for j, fi in enumerate(model["idx"]):
        name = feats[fi]
        v = feat.get(name, 0.0)
        if v is None or v != v:
            v = 0.0
        z += model["w"][j] * (v - model["mu"][j]) / (model["sd"][j] + EPS)
    return _sigmoid(z)


def _weekly_index(weekly, day):
    """最近一根「已结束」周K 的下标（day 严格早于当前日K）"""
    if not weekly:
        return -1
    lo, hi, ans = 0, len(weekly) - 1, -1
    key = str(day)[:10]
    while lo <= hi:
        mid = (lo + hi) // 2
        if str(weekly[mid]["day"])[:10] < key:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def predict_series(bars, weekly, node, kind):
    """
    逐根算概率（画曲线 / 算分位）。

    纯 Python 逐根重算代价高，两个优化：
      1. 只算最后 RANK_WIN 根，且步长 STEP（分位粒度 1/80 足够）
      2. 周K 特征按「用到第几根周K」缓存 —— 日K 每 5 根才跨一周，命中率 ~80%
    """
    prof = _load()
    feats = prof.get("features", [])
    sec = prof.get("sectors", {}).get(node)
    if not sec or kind not in sec:
        return None
    models = {dn: sec[kind][dn] for dn in ("up", "down") if dn in sec[kind]}
    if not models:
        return None

    out = {"up": [], "down": []}
    start = max(200, len(bars) - RANK_WIN)
    step = 2 if RANK_WIN > 120 else 1
    wcache = {}
    for i in range(start, len(bars), step):
        sub = bars[:i + 1]
        f = _core_features(sub)
        if weekly:
            wi = _weekly_index(weekly, sub[-1]["day"])
            if wi < 130:
                f.update({("w_" + k): 0.0 for k in WEEKLY_KEYS})
            else:
                if wi not in wcache:
                    wcache[wi] = _core_features(weekly[:wi + 1])
                wf = wcache[wi]
                f.update({("w_" + k): wf.get(k, 0.0) for k in WEEKLY_KEYS})
        for dn, m in models.items():
            out[dn].append(_predict(f, feats, m))
    return out


# ============================================================ 趋势分段
def detect_phases(bars, window=20, min_len=20, min_amp=0.12):
    """
    Pagan-Sossounov 删失局部极值：找出事后确认的趋势段。
    用于展示「现在处于哪一段趋势的第几根」，以及历史拐点位置。
    """
    n = len(bars)
    px = [b["close"] for b in bars]
    if n < 3 * window:
        return {"phases": [], "turns": []}

    # 候选局部极值
    cand = []
    for i in range(window, n - window):
        seg_l = px[i - window:i]
        seg_r = px[i + 1:i + 1 + window]
        if px[i] >= max(seg_l) and px[i] >= max(seg_r):
            cand.append((i, px[i], 1))
        elif px[i] <= min(seg_l) and px[i] <= min(seg_r):
            cand.append((i, px[i], -1))

    # 强制峰谷交替
    alt = []
    for it in cand:
        if alt and alt[-1][2] == it[2]:
            if (it[2] == 1 and it[1] >= alt[-1][1]) or (it[2] == -1 and it[1] <= alt[-1][1]):
                alt[-1] = it
        else:
            alt.append(it)

    if not alt:
        return {"phases": [], "turns": []}
    if alt[0][0] != 0:
        alt.insert(0, (0, px[0], -alt[0][2]))
    if alt[-1][0] != n - 1:
        alt.append((n - 1, px[-1], -alt[-1][2]))

    # 删失：太短或太小就删掉并合并
    for _ in range(60):
        if len(alt) <= 2:
            break
        changed = False
        for i in range(1, len(alt) - 1):
            idx, p, sg = alt[i]
            pidx, pp, _ = alt[i - 1]
            if (idx - pidx) < min_len or abs(p / max(pp, 1e-9) - 1.0) * 100 < min_amp * 100:
                del alt[i]
                # 重新交替
                nalt = []
                for it in alt:
                    if nalt and nalt[-1][2] == it[2]:
                        if (it[2] == 1 and it[1] >= nalt[-1][1]) or \
                           (it[2] == -1 and it[1] <= nalt[-1][1]):
                            nalt[-1] = it
                    else:
                        nalt.append(it)
                alt = nalt
                changed = True
                break
        if not changed:
            break

    phases, turns = [], []
    for i in range(len(alt) - 1):
        s, sp, ssg = alt[i]
        e, ep, _ = alt[i + 1]
        phases.append({
            "type": "up" if ssg == -1 else "down",
            "start": s, "end": e, "bars": e - s,
            "start_day": str(bars[s]["day"])[:10], "end_day": str(bars[e]["day"])[:10],
            "chg": round((ep / max(sp, 1e-9) - 1) * 100, 2),
        })
    for i in range(1, len(alt) - 1):
        turns.append({"i": alt[i][0], "day": str(bars[alt[i][0]]["day"])[:10],
                      "type": "top" if alt[i][2] == 1 else "bottom",
                      "price": round(alt[i][1], 3)})
    return {"phases": phases, "turns": turns}


# ============================================================ 主入口
def analyze(bars, name="", sector_name="", industry="", scale=240, weekly=None,
            with_series=True, symbol=""):
    """
    bars: 等长 dict 列表 [{day,open,high,low,close,volume}]
    返回前端可直接消费的结构；不可用时返回 {"ok": False, "reason": ...}
    """
    prof = _load()
    if not prof.get("sectors"):
        return {"ok": False, "reason": "未找到标定参数（data/turning_profiles.json）"}
    if not bars or len(bars) < 260:
        return {"ok": False, "reason": "K线不足 260 根，无法做转折点判断"}

    kind = SCALE_KIND.get(scale, "day")
    kind_note = "" if scale in SCALE_KIND else "（非日/周周期，按日线模型估算）"

    node, how = match_sector(name, sector_name, industry, symbol)
    feats = prof.get("features", [])
    sec = prof["sectors"].get(node) if node else None

    # 匹配不到 → 用同资金属性的平均参数兜底
    fallback = None
    if not sec:
        for tag, grp in (prof.get("fallback") or {}).items():
            if kind in grp:
                fallback = (tag, grp)
                break

    if sec and kind in sec and sec[kind]:
        models = sec[kind]
        meta = {"sector": sec["name"], "tag": sec["tag"], "node": node,
                "matched": True, "how": how, "fallback": False}
    elif fallback:
        tag, grp = fallback
        models = grp[kind]
        meta = {"sector": "通用（%s 型平均）" % tag, "tag": tag, "node": None,
                "matched": False, "how": "未匹配到已标定板块，用同资金属性平均参数",
                "fallback": True}
    else:
        return {"ok": False, "reason": "「%s」所属板块未标定，且无可用兜底参数" % (name or "该标的")}

    # ---- 特征
    if kind == "week":
        # 周线模型本身不含周K共振列，不需要再合成周K
        feat = _core_features(bars)
        feat.update({("w_" + k): 0.0 for k in WEEKLY_KEYS})
        weekly = None
    else:
        if weekly is None:
            weekly = to_weekly(bars)
        feat = build_features(bars, weekly)

    # ---- 当前概率
    cur = {}
    for dn in ("up", "down"):
        m = models.get(dn)
        if not m:
            continue
        p = _predict(feat, feats, m)
        cur[dn] = {
            "p": round(p, 4),
            "thr": round(float(m["thr"]), 4),
            "sig": bool(p >= m["thr"]),
            "prec": round(float(m.get("prec", 0)), 4),
            "recall": round(float(m.get("recall", 0)), 4),
            "n_sig": int(m.get("n_sig", 0)),
            "lead": m.get("lead"),
            "base": round(float(m.get("base", 0)), 4),
        }

    # 兜底参数不给出「触发」—— 模型都没针对这个板块标定过，说触发是误导
    if meta["fallback"]:
        for v in cur.values():
            v["sig"] = False
            v["suppressed"] = True

    # ---- 概率分位（比绝对阈值可靠）
    series = None
    if with_series:
        try:
            series = predict_series(bars, weekly, node, kind) if node else None
        except Exception:                                   # noqa: BLE001
            series = None
    for dn in cur:
        if series and series.get(dn):
            win = series[dn][-RANK_WIN:]
            cur[dn]["pct"] = round(_rank_pct(win, cur[dn]["p"]), 4)
            cur[dn]["rank_sig"] = bool(cur[dn]["pct"] >= RANK_THR)
        else:
            cur[dn]["pct"] = None
            cur[dn]["rank_sig"] = False

    # ---- 市场状态（五态）
    state = _state(feat)

    # ---- 趋势分段
    tag = meta["tag"]
    amp = {"trend": 0.12, "cycle": 0.15, "growth": 0.18, "defense": 0.10}.get(tag, 0.15)
    ph = detect_phases(bars, window=20 if kind == "day" else 10,
                       min_len=20 if kind == "day" else 12, min_amp=amp)

    # ---- 当前处于哪一段
    cur_phase = None
    if ph["phases"]:
        last = ph["phases"][-1]
        cur_phase = {
            "type": last["type"], "bars": last["bars"],
            "start_day": last["start_day"], "chg": last["chg"],
            "progress": round(min(1.0, last["bars"] / 120.0), 2),
        }

    return {
        "ok": True,
        "scale": scale, "kind": kind, "kind_note": kind_note,
        "meta": meta,
        "state": state,
        "rev": cur,
        "phase": cur_phase,
        "phases": ph["phases"][-8:],
        "turns": ph["turns"][-8:],
        "series": ({"up": [round(x, 4) for x in series["up"]],
                    "down": [round(x, 4) for x in series["down"]],
                    "start": max(0, len(bars) - RANK_WIN)}
                   if series else None),
        "evidence": _evidence(feat, cur, state, cur_phase),
        "note": _note(meta, cur),
    }


def _state(feat):
    """五态市场状态（与标定端同一套打分逻辑）"""
    s_trend = (feat["ema_align"] * 0.4
               + math.tanh(feat["slope_t20"] / 2.0) * 0.3
               + math.tanh(feat["ema_bias60"] * 8.0) * 0.3)
    s_pos = math.tanh(feat["zscore60"] / 1.5) * 0.5 + (feat["pos_120"] - 0.5) * 1.0
    s_mom = (math.tanh(feat["roc20"] * 12.0) * 0.5
             + (feat["rsi14"] - 50.0) / 50.0 * 0.3
             + math.tanh(feat["macd_hist_n"] / 2.0) * 0.2)
    score = max(-1.0, min(1.0, 0.45 * s_trend + 0.25 * s_pos + 0.30 * s_mom))
    names = ["强势下跌", "弱势下跌", "横盘震荡", "弱势上涨", "强势上涨"]
    idx = 0 if score <= -0.55 else 1 if score <= -0.18 else 2 if score <= 0.18 else 3 if score <= 0.55 else 4
    return {"name": names[idx], "score": round(score, 3),
            "adx": round(feat["adx14"], 1),
            "atr_pct": round(feat["atr_pct"] * 100, 2),
            "rsi": round(feat["rsi14"], 1)}


def _evidence(feat, cur, state, cur_phase):
    ev = []
    if feat["ll_days"] >= 30 and feat["pos_120"] < 0.3:
        ev.append("已 %d 根未创新低，处于 120 根区间下沿（%.0f%%）"
                  % (int(feat["ll_days"]), feat["pos_120"] * 100))
    if feat["hh_days"] >= 30 and feat["pos_120"] > 0.7:
        ev.append("已 %d 根未创新高，处于 120 根区间上沿（%.0f%%）"
                  % (int(feat["hh_days"]), feat["pos_120"] * 100))
    if feat["pv_div"] > 0.02:
        ev.append("价跌量缩（背离度 %.3f），卖压衰竭" % feat["pv_div"])
    if feat["bb_width_q"] < 0.25:
        ev.append("布林带收窄至近 120 根 %.0f%% 分位，变盘窗口" % (feat["bb_width_q"] * 100))
    if feat["rsi_div"] < -0.05:
        ev.append("RSI 与价格背离（%.2f）" % feat["rsi_div"])
    if feat["macd_div"] < -0.05:
        ev.append("MACD 与价格背离（%.2f）" % feat["macd_div"])
    if feat["ema_align"] >= 0.66:
        ev.append("均线多头排列")
    elif feat["ema_align"] <= -0.66:
        ev.append("均线空头排列")
    if feat["adx14"] > 30:
        ev.append("ADX %.0f，趋势强度高" % feat["adx14"])
    if feat["lower_shadow"] > 0.35:
        ev.append("长下影线（%.0f%%），下方有承接" % (feat["lower_shadow"] * 100))
    if feat["upper_shadow"] > 0.35:
        ev.append("长上影线（%.0f%%），上方有抛压" % (feat["upper_shadow"] * 100))
    # 周线共振
    if "w_ema_align" in feat:
        if feat["w_ema_align"] <= -0.66 and cur.get("up", {}).get("p", 0) > 0.5:
            ev.append("日线出现底部迹象但周线仍空头排列 —— 反弹级别有限")
        elif feat["w_ema_align"] >= 0.66 and cur.get("down", {}).get("p", 0) > 0.5:
            ev.append("日线出现顶部迹象但周线仍多头排列 —— 大概率是回调不是反转")
    if cur_phase:
        ev.append("当前处于%s段第 %d 根（累计 %+.1f%%）"
                  % ("上涨" if cur_phase["type"] == "up" else "下跌",
                     cur_phase["bars"], cur_phase["chg"]))
    return ev[:7]


def _note(meta, cur):
    bits = []
    if meta["fallback"]:
        bits.append("⚠ 该标的所属板块未单独标定，使用「%s」的平均参数，可信度低于已标定板块；"
                    "因此不给出触发信号，概率仅作方向参考。" % meta["sector"])
    if cur:
        precs = [v["prec"] for v in cur.values() if v.get("prec")]
        if precs:
            bits.append("该板块历史样本外准确率约 %.0f%%（随机基线约 %.0f%%）—— "
                        "这是「命中拐点」的准确率，不是「能赚钱」的准确率。"
                        % (sum(precs) / len(precs) * 100,
                           sum(v.get("base", 0.07) for v in cur.values()) / len(cur) * 100))
        bits.append("绝对阈值跨时段不可迁移，优先看「分位」：分位 ≥95% 表示这是近一年最像反转的 5% 时刻。")
    return bits


# ============================================================ 便捷
def quick(bars, name="", scale=240, symbol=""):
    r = analyze(bars, name=name, scale=scale, with_series=False, symbol=symbol)
    if not r.get("ok"):
        return r
    up, dn = r["rev"].get("up", {}), r["rev"].get("down", {})
    return {
        "ok": True, "sector": r["meta"]["sector"], "state": r["state"]["name"],
        "rev_up": up.get("p"), "rev_down": dn.get("p"),
        "sig_up": up.get("sig"), "sig_down": dn.get("sig"),
        "phase": (r["phase"]["type"] if r["phase"] else None),
    }
