# -*- coding: utf-8 -*-
"""
板块分类 · sectors.py
=====================
目标：把「板块」做细 —— 存储芯片、半导体材料、半导体设备、云计算、AI 应用、
机器人执行器、医疗器械、保险…… 而不是只有 49 个粗行业。

数据源：
  * 东方财富 push2（行业 496 个 + 概念 516 个，含三级细分）—— 首选
  * 新浪 newFLJK 概念/行业（175 + 84）—— 兜底

★ 东财 push2 会按 **TLS 指纹** 拦截 urllib（RemoteDisconnected），
  换 header、加 gzip、降 SECLEVEL 都没用，curl 却能正常拿到。
  所以这里用 curl 子进程（Windows 10+ / macOS / Linux / Termux 都自带）。

分层：
  主题（半导体 / AI算力 / 机器人 / 医药医疗 / 金融 …）
    └─ 细分板块（存储芯片 / 半导体材料 / 半导体设备 / CPO / 减速器 …）
"""

import json
import re
import subprocess
import threading
import time

from . import sina

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# ---------------------------------------------------------------- 主题归类
#
# 顺序即优先级：越具体的放前面。
# 「半导体」必须排在「电子」之前，否则「半导体材料」会被「电子」吃掉。
THEMES = [
    ("半导体", ["半导体", "芯片", "存储", "光刻", "封测", "晶圆", "集成电路",
                "EDA", "MCU", "IGBT", "碳化硅", "氮化镓", "硅片", "光刻胶",
                "第三代半导体", "先进封装", "chiplet", "HBM", "海思",
                "电子元件", "分立器件", "被动元件"]),
    ("AI算力", ["算力", "人工智能", "AI", "大模型", "云计算", "数据中心",
                "CPO", "光模块", "液冷", "服务器", "IDC", "PCB", "AIGC",
                "多模态", "智能体", "算力租赁", "百度", "互联网", "宽带",
                "安防", "物联网"]),
    ("软件信创", ["软件", "信创", "信息安全", "网络安全", "数据要素", "数字经济",
                  "区块链", "操作系统", "办公", "工业互联网", "SaaS", "鸿蒙",
                  "电商", "电子支付"]),
    ("通信", ["通信", "5G", "6G", "卫星", "北斗", "光通信", "光纤", "射频",
              "天线", "移动"]),
    ("消费电子", ["消费电子", "苹果", "华为", "小米", "VR", "AR", "MR", "折叠屏",
                  "智能穿戴", "面板", "触摸屏", "声学", "摄像头", "光学",
                  "无线耳机", "智能家居", "家电"]),
    ("机器人", ["机器人", "减速器", "伺服", "执行器", "机器视觉", "工业母机",
                "数控", "丝杠", "传感器", "谐波", "灵巧手", "人形", "智能机器",
                "3D打印", "通用设备", "专用设备", "仪器仪表", "电气机械",
                "其他制造业", "金属制品", "智能制造"]),
    ("医药医疗", ["医药", "医疗", "生物", "疫苗", "CXO", "CRO", "创新药", "中药",
                  "化学制药", "原料药", "器械", "医院", "诊断", "基因", "医美",
                  "血液", "眼科", "牙科", "药", "卫生", "抗癌", "免疫", "细菌",
                  "流感", "维生素", "保健品"]),
    ("金融", ["银行", "保险", "证券", "券商", "金融", "期货", "信托", "支付",
              "多元金融", "参股", "资本市场", "租赁", "商务服务"]),
    ("新能源", ["光伏", "风电", "风能", "储能", "锂", "钠", "电池", "氢", "充电",
                "核电", "新能源", "硅料", "组件", "逆变器", "电解液", "正极",
                "负极", "隔膜", "钙钛矿", "TOPCon", "HJT", "智能电网",
                "地热", "页岩气", "油气", "太阳能", "高压快充", "碳中和",
                "节能环保", "低碳"]),
    ("汽车", ["汽车", "整车", "零部件", "智能驾驶", "无人驾驶", "车联网",
              "轮胎", "汽车电子", "一体化压铸"]),
    ("军工", ["军工", "国防", "航天", "航空", "船舶", "兵器", "大飞机",
              "军民融合", "海工"]),
    ("消费", ["白酒", "食品", "饮料", "旅游", "酒店", "免税", "零售", "纺织",
              "服装", "美容", "婴童", "宠物", "家居", "家具", "珠宝", "预制菜",
              "餐饮", "啤酒", "乳", "奢侈品", "住宿", "皮革", "木材", "印刷",
              "体育", "文化", "教育"]),
    ("周期资源", ["钢铁", "煤炭", "有色", "化工", "水泥", "建材", "稀土", "黄金",
                  "铜", "铝", "石油", "化学", "化纤", "橡胶", "塑料", "玻璃",
                  "造纸", "钛", "磷", "氟", "小金属", "碳纤维", "石墨烯",
                  "超导", "聚氨酯", "草甘膦", "黑色金属", "非金属矿",
                  "开采辅助", "稀缺资源", "涉矿", "新材料", "矿物"]),
    ("地产基建", ["房地产", "建筑", "基建", "水利", "装修", "工程",
                  "钢结构", "园林", "水泥"]),
    ("农业", ["农业", "种业", "养殖", "猪", "禽", "鸡肉", "饲料", "渔业",
              "林业", "化肥", "农药", "转基因", "畜牧", "水产", "农、林",
              "农林"]),
    ("传媒", ["传媒", "游戏", "影视", "出版", "广告", "院线",
              "短剧", "IP", "文化艺术"]),
    ("公用事业", ["电力", "燃气", "水务", "环保", "交通", "运输", "港口",
                  "机场", "高速", "铁路", "物流", "污水处理", "固废",
                  "空气治理", "垃圾分类", "水的生产", "公共设施", "生态保护",
                  "废弃资源", "邮政", "仓储", "社会工作"]),
    ("其他", []),
]

THEME_ORDER = [t for t, _ in THEMES]

# 明确不要的「伪板块」：事件类 / 持仓类 / 地域政策类，都不是行业细分
_BLACKLIST = (
    # 事件 / 交易属性
    "昨日", "今日", "涨停", "跌停", "连板", "打板", "融资融券", "沪股通",
    "深股通", "转债", "标的", "重仓", "持股", "预增", "预降", "解禁",
    "送转", "摘帽", "ST", "次新", "破净", "高送转", "股权激励", "回购",
    "增持", "举牌", "分拆", "重组", "壳资源", "低价股", "高价股", "百元股",
    "AH股", "AB股", "GDR", "B股", "H股", "MSCI", "富时", "标普道琼斯",
    "整体上市", "资产注入", "国企改革", "未股改", "业绩预", "三板精选",
    "外资背景", "高校背景", "专精特新", "科创50", "超大盘", "央企50",
    "恒大概念", "股期概念", "出口退税", "循环经济", "文化振兴",
    # 地域 / 区域政策
    "上海本地", "深圳本地", "雄安", "京津冀", "成渝", "长株潭", "皖江",
    "海峡西岸", "海南自贸", "三沙", "图们江", "朝鲜", "陕甘宁", "振兴沈阳",
    "武汉规划", "前海", "黄河三角", "海上丝路", "东亚自贸", "日韩贸易",
    "天津自贸", "上海自贸", "自贸区", "沿海发展", "内贸规划", "乡村振兴",
    "土地流转", "水域改革", "迪士尼", "赛马", "博彩", "中韩",
)


def theme_of(name):
    for theme, kws in THEMES:
        for kw in kws:
            if kw in name:
                return theme
    return "其他"


def _blocked(name):
    return any(b in name for b in _BLACKLIST)


# ---------------------------------------------------------------- 自建细分板块
#
# 新浪的概念板块里没有「存储芯片 / 半导体材料 / 云计算 / 医疗器械」这种精确细分
# （只有一个「华为海思」），东方财富倒是有 496 个行业 + 516 个概念，
# 但它按 TLS 指纹拦 Python，且频繁限流（curl 也会 56 断连），不适合做常驻数据源。
#
# 所以这里手工维护 9 个高频细分板块的成分股，行情用等权实时计算。
# 成分股都是逐个调新浪行情接口验证过的有效代码。
# 缺点：静态列表，新股/退市需要偶尔更新；优点：稳、准、可控。

CUSTOM_BOARDS = {
    "存储芯片": ("半导体", ["603986", "300223", "688008", "301308", "688525",
                            "001309", "688766", "688110", "688416", "688123"]),
    "半导体材料": ("半导体", ["688126", "605358", "002129", "688019", "002409",
                              "300666", "300054", "603650", "300655", "300236",
                              "688268", "300346"]),
    "半导体设备": ("半导体", ["002371", "688012", "688072", "688082", "688120",
                              "688037", "300567", "300604", "600641", "603690",
                              "300260", "688596"]),
    "芯片设计": ("半导体", ["603501", "300782", "300661", "688536", "688052",
                            "688099", "603893", "300458", "300613", "300327"]),
    "封装测试": ("半导体", ["600584", "002156", "002185", "603005", "688362", "688216"]),
    "云计算": ("AI算力", ["000977", "000938", "600588", "688111", "300454",
                          "300383", "603881", "600845", "688158", "688316"]),
    "AI应用": ("AI算力", ["002230", "300418", "601360", "300624", "300459",
                          "300364", "603533", "002362", "688787", "688327",
                          "688207", "688088"]),
    "医疗器械": ("医药医疗", ["300760", "688271", "300003", "002223", "600055",
                              "300633", "688212", "688617", "688029", "688016",
                              "688050", "300595"]),
    "保险": ("金融", ["601318", "601628", "601601", "601336", "601319"]),
}


def _build_custom():
    """自建板块：批量查成分股，等权算涨跌幅，取领涨股"""
    codes = []
    for _, (_, lst) in CUSTOM_BOARDS.items():
        codes.extend(lst)
    syms = [sina.normalize_code(c) for c in codes]
    syms = [s for s in syms if s]
    quotes = sina.fetch_quotes(syms) if syms else {}

    out = []
    for name, (theme, lst) in CUSTOM_BOARDS.items():
        qs = []
        for c in lst:
            q = quotes.get(sina.normalize_code(c))
            if q and q.get("price"):
                qs.append(q)
        if not qs:
            continue
        pcts = [q.get("change_pct", 0.0) for q in qs]
        lead = max(qs, key=lambda q: q.get("change_pct", 0.0))
        up = sum(1 for p in pcts if p > 0)
        out.append({
            "code": "cb_" + name,
            "name": name,
            "change_pct": round(sum(pcts) / len(pcts), 2),
            "amount": sum(q.get("amount", 0) for q in qs),
            "turnover": 0.0,
            "net_inflow": 0.0,
            "up": up,
            "down": len(pcts) - up,
            "lead_name": lead.get("name", ""),
            "lead_pct": round(lead.get("change_pct", 0.0), 2),
            "lead_code": (lead.get("symbol") or "")[2:],
            "kind": "custom",
            "theme": theme,
            "count": len(qs),
        })
    return out


# ---------------------------------------------------------------- 抓取

def _curl_json(url, timeout=12):
    """用 curl 子进程拿 JSON（东财拦 urllib 的 TLS 指纹）"""
    try:
        p = subprocess.run(
            ["curl", "-s", "--compressed", "--max-time", str(timeout),
             "-H", "User-Agent: " + _UA,
             "-H", "Referer: https://quote.eastmoney.com/",
             "-H", "Accept: application/json, text/plain, */*",
             url],
            capture_output=True, timeout=timeout + 4,
        )
        if p.returncode == 0 and p.stdout:
            return json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        pass
    return None


_EM_URL = ("https://push2.eastmoney.com/api/qt/clist/get"
           "?pn=1&pz=%d&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:%d"
           "&fields=f12,f14,f3,f6,f8,f62,f104,f105,f128,f136,f140")

_FIELDS = ("f12", "f14", "f3", "f6", "f8", "f62", "f104", "f105",
           "f128", "f136", "f140")


def _fetch_em(kind, size=600):
    """kind: 2=行业板块 3=概念板块"""
    d = _curl_json(_EM_URL % (size, kind))
    if not d or not d.get("data") or not d["data"].get("diff"):
        return []
    out = []
    for x in d["data"]["diff"]:
        name = (x.get("f14") or "").strip()
        if not name or _blocked(name):
            continue
        out.append({
            "code": x.get("f12", ""),
            "name": name,
            "change_pct": _f(x.get("f3")),
            "amount": _f(x.get("f6")),
            "turnover": _f(x.get("f8")),
            "net_inflow": _f(x.get("f62")),
            "up": int(_f(x.get("f104"))),
            "down": int(_f(x.get("f105"))),
            "lead_name": x.get("f128") or "",
            "lead_pct": _f(x.get("f136")),
            "lead_code": x.get("f140") or "",
            "kind": "industry" if kind == 2 else "concept",
        })
    return out


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if v == v else d
    except Exception:
        return d


_PAIR = re.compile(r'"([\w]+)":"([^"]*)"')


def _fetch_sina(kind):
    """兜底：新浪 newFLJK（class=概念 175 个 / hangye=证监会行业 84 个）"""
    url = "https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=" + kind
    txt = sina.http_get(url, encoding="gbk", timeout=10)
    if not txt:
        return []
    out = []
    for m in _PAIR.finditer(txt):
        p = m.group(2).split(",")
        if len(p) < 13:
            continue
        name = p[1].strip()
        if not name or _blocked(name):
            continue
        out.append({
            "code": m.group(1), "name": name,
            "change_pct": _f(p[5]), "amount": _f(p[7]),
            "turnover": 0.0, "net_inflow": 0.0,
            "up": 0, "down": 0,
            "lead_name": p[12] if len(p) > 12 else "",
            "lead_pct": _f(p[9]), "lead_code": p[8] if len(p) > 8 else "",
            "kind": "concept" if kind == "class" else "industry",
        })
    return out


# ---------------------------------------------------------------- 缓存

_cache = {"ts": 0.0, "data": None}
_lock = threading.Lock()
TTL = 45          # 板块数据 45 秒一刷


def all_boards(force=False):
    """全部板块（行业 + 概念），已归入主题、已过滤伪板块"""
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["ts"] < TTL:
            return _cache["data"]

    # ★ 只用新浪。东财虽然粒度更细（496 行业 + 516 概念），但：
    #   1) 按 TLS 指纹拦 Python，时通时不通，限流后 curl 也 56 断连
    #   2) 板块质量不稳（会出现「反转股」「2026三季报首亏」这种垃圾板块）
    #   3) 它的 BK 代码没法喂给新浪的 getHQNodeData 拿成分股
    # 新浪的 gn_/hangye_ 代码可以直接查成分股，链路是通的，所以以新浪为准。
    industry = _fetch_sina("hangye")
    concept = _fetch_sina("class")
    source = "sina"

    boards = industry + concept + _build_custom()
    for b in boards:
        if not b.get("theme"):
            b["theme"] = theme_of(b["name"])

    boards.sort(key=lambda x: -x["change_pct"])

    # 主题汇总
    agg = {}
    for b in boards:
        t = b["theme"]
        a = agg.setdefault(t, {"key": t, "name": t, "count": 0, "sum": 0.0,
                               "amount": 0.0, "up": 0, "down": 0})
        a["count"] += 1
        a["sum"] += b["change_pct"]
        a["amount"] += b["amount"]
        a["up"] += b["up"]
        a["down"] += b["down"]
    themes = []
    for t in THEME_ORDER:
        a = agg.get(t)
        if not a or not a["count"]:
            continue
        themes.append({
            "key": t, "name": t, "count": a["count"],
            "change_pct": round(a["sum"] / a["count"], 2),
            "amount": a["amount"], "up": a["up"], "down": a["down"],
        })
    themes.sort(key=lambda x: -x["change_pct"])

    data = {
        "ok": True,
        "source": source,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(boards),
        "themes": themes,
        "boards": boards,
    }
    with _lock:
        _cache["ts"] = time.time()
        _cache["data"] = data
    return data


def by_theme(theme=None, kind=None, sort="change_pct", limit=120):
    """按主题/类型筛选"""
    d = all_boards()
    items = d["boards"]
    if theme and theme not in ("全部", "all"):
        items = [b for b in items if b["theme"] == theme]
    if kind and kind != "all":
        items = [b for b in items if b["kind"] == kind]
    key = {"change_pct": "change_pct", "amount": "amount",
           "turnover": "turnover", "net_inflow": "net_inflow"}.get(sort, "change_pct")
    items = sorted(items, key=lambda x: -x.get(key, 0))
    return {
        "ok": True,
        "themes": d["themes"],
        "total": len(items),
        "source": d["source"],
        "updated": d["updated"],
        "items": items[:limit],
    }


# ---------------------------------------------------------------- 板块成分股

def board_stocks(code, limit=200):
    """
    取某个板块的全部成分股。

    * 自建板块（cb_xxx）→ 直接读 CUSTOM_BOARDS 里的代码，再批量查行情
    * 新浪板块（gn_xxx / hangye_xxx）→ Market_Center.getHQNodeData?node=xxx
      ★ 这个接口只认**真实存在**的节点代码，随便编一个（gn_5g / gn_rgzn）会返回空数组
    """
    code = (code or "").strip()
    if not code:
        return {"ok": False, "reason": "缺少板块代码"}

    # 板块名 + 主题
    name, theme = code, ""
    for b in all_boards()["boards"]:
        if b["code"] == code:
            name, theme = b["name"], b.get("theme", "")
            break

    rows = []
    if code.startswith("cb_"):
        spec = CUSTOM_BOARDS.get(code[3:])
        if not spec:
            return {"ok": False, "reason": "未知的自建板块：%s" % code}
        theme, codes = spec
        syms = [sina.normalize_code(c) for c in codes]
        quotes = sina.fetch_quotes([s for s in syms if s])
        for c in codes:
            q = quotes.get(sina.normalize_code(c))
            if not q:
                continue
            rows.append({
                "symbol": q.get("symbol", ""),
                "code": c,
                "name": q.get("name", ""),
                "price": q.get("price", 0),
                "change": q.get("change", 0),
                "change_pct": q.get("change_pct", 0),
                "amount": q.get("amount", 0),
                "turnover": q.get("turnover", 0),
                "volume": q.get("volume", 0),
            })
    else:
        raw = sina.fetch_market_list(200, "changepercent", code)
        for r in raw:
            rows.append({
                "symbol": r.get("symbol", ""),
                "code": r.get("code", ""),
                "name": r.get("name", ""),
                "price": _f(r.get("trade")),
                "change": _f(r.get("pricechange")),
                "change_pct": _f(r.get("changepercent")),
                "amount": _f(r.get("amount")),
                "turnover": _f(r.get("turnoverratio")),
                "volume": _f(r.get("volume")),
            })

    rows.sort(key=lambda x: -x["change_pct"])
    up = sum(1 for r in rows if r["change_pct"] > 0)
    avg = sum(r["change_pct"] for r in rows) / len(rows) if rows else 0.0
    return {
        "ok": True,
        "code": code,
        "name": name,
        "theme": theme,
        "total": len(rows),
        "up": up,
        "down": len(rows) - up,
        "avg_pct": round(avg, 2),
        "items": rows[:limit],
    }
