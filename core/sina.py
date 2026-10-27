# -*- coding: utf-8 -*-
"""
新浪财经数据抓取层
==================
纯标准库实现（urllib），零第三方依赖。

数据源全部来自新浪财经：
  * 实时行情      hq.sinajs.cn/list=sh600519
  * 指数简版      hq.sinajs.cn/list=s_sh000001
  * 场外基金净值  hq.sinajs.cn/list=f_110022
  * 日/周/月/分钟K money.finance.sina.com.cn ... CN_MarketData.getKLineData
  * 行业板块      vip.stock.finance.sina.com.cn/q/view/newSinaHy.php
  * 全市场列表    vip.stock.finance.sina.com.cn ... Market_Center.getHQNodeData
辅助（仅用于补流通股本，算换手率）：push2.eastmoney.com 单股快照。
"""

import json
import re
import time
import threading
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import config

# ------------------------------------------------------------------ 基础

_UA_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Referer": "https://finance.sina.com.cn",
    "Accept": "*/*",
}

_local = threading.local()


def _opener():
    o = getattr(_local, "opener", None)
    if o is None:
        o = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        _local.opener = o
    return o


def http_get(url, encoding="utf-8", timeout=None, headers=None):
    """带重试的 GET。返回解码后的字符串；失败返回 None。"""
    timeout = timeout or config.HTTP_TIMEOUT
    hdrs = dict(_UA_HEADERS)
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(config.HTTP_RETRY + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            raw = _opener().open(req, timeout=timeout).read()
            return raw.decode(encoding, errors="replace")
        except Exception as e:                      # noqa: BLE001
            last = e
            if attempt < config.HTTP_RETRY:
                time.sleep(0.35 * (attempt + 1))
    return None


# ------------------------------------------------------------------ 代码规范化

INDEX_CODES = {
    "sh000001", "sh000016", "sh000300", "sh000688", "sh000905", "sh000852",
    "sz399001", "sz399006", "sz399005", "sz399300", "sz399905",
}

# 外围市场前缀
GLOBAL_PREFIX = ("gb_", "rt_hk", "hk", "hf_", "nf_", "int_", "fx_")

_PREFIX_RE = re.compile(r"^(sh|sz|bj)", re.I)


def is_global(symbol):
    return bool(symbol) and symbol.startswith(GLOBAL_PREFIX)


def normalize_code(raw):
    """把用户输入的代码统一成 sh600519 / sz000001 / f_110022 / gb_aapl / hf_GC 形式。"""
    if not raw:
        return None
    orig = str(raw).strip().replace(" ", "")
    s = orig.lower()
    if not s:
        return None
    # 外围市场：区分大小写，用小写别名映射回标准写法
    if s.startswith(GLOBAL_PREFIX):
        return config.GLOBAL_ALIAS.get(s, orig)
    # 已带 f_ 前缀（场外基金）
    if s.startswith("f_"):
        return s
    if _PREFIX_RE.match(s):
        p, body = s[:2], s[2:]
        if body.isdigit():
            return p + body
        return None
    # 纯数字
    if not s.isdigit():
        return None
    if len(s) != 6:
        return None
    c2, c1 = s[:2], s[0]
    if c1 in "68" or c2 in ("60", "68", "90"):
        return "sh" + s
    if c2 in ("00", "30", "20", "15", "16", "18", "13", "12"):
        return "sz" + s
    if c2 in ("43", "83", "87", "88", "92") or c1 in ("4", "8"):
        return "bj" + s
    return "sh" + s


def is_index(symbol):
    return symbol in INDEX_CODES


_ETF_PREFIX_SH = ("510", "511", "512", "513", "515", "516", "517", "518",
                  "560", "561", "562", "563", "588", "589", "501", "502", "506")
_ETF_PREFIX_SZ = ("159", "160", "161", "162", "163", "164", "165", "166",
                  "167", "168", "169")


def is_fund(symbol):
    """ETF / LOF / 场外基金。注意 000001 是平安银行而非基金，不做模糊匹配。"""
    if symbol.startswith("f_"):
        return True
    body = symbol[2:] if _PREFIX_RE.match(symbol) else symbol
    if len(body) != 6 or not body.isdigit():
        return False
    if symbol.startswith("sh") and body[:3] in _ETF_PREFIX_SH:
        return True
    if symbol.startswith("sz") and body[:3] in _ETF_PREFIX_SZ:
        return True
    return False


def market_of(symbol):
    if symbol.startswith("sh"):
        return "上海"
    if symbol.startswith("sz"):
        return "深圳"
    if symbol.startswith("bj"):
        return "北京"
    return "场外"


# ------------------------------------------------------------------ 实时行情

_QUOTE_RE = re.compile(r'hq_str_([\w$.]+)="([^"]*)"')


def _f(x, default=0.0):
    try:
        v = float(x)
        return v if v == v else default          # 过滤 nan
    except Exception:
        return default


def fetch_quotes(symbols):
    """
    批量拉实时行情。返回 {symbol: quote_dict}
    股票字段：name open prev_close price high low bid ask volume amount 五档 date time
    指数走 s_ 简版：name price change changepct volume amount
    """
    if not symbols:
        return {}
    out = {}
    stock_syms, index_syms, fund_syms = [], [], []
    for s in symbols:
        if s.startswith("f_"):
            fund_syms.append(s)
        elif is_index(s):
            index_syms.append(s)
        else:
            stock_syms.append(s)

    # ---- 指数简版
    if index_syms:
        q = ",".join("s_" + s for s in index_syms)
        txt = http_get("https://hq.sinajs.cn/list=" + q, encoding="gbk")
        if txt:
            for m in _QUOTE_RE.finditer(txt):
                key = m.group(1)[2:]                     # 去掉 s_
                p = m.group(2).split(",")
                if len(p) < 6:
                    continue
                price = _f(p[1]); chg = _f(p[2]); pct = _f(p[3])
                prev = price - chg
                out[key] = {
                    "symbol": key, "name": p[0], "kind": "index",
                    "price": price, "change": chg, "change_pct": pct,
                    "prev_close": round(prev, 4),
                    "open": round(prev, 4), "high": price, "low": price,
                    "volume": _f(p[4]) * 100, "amount": _f(p[5]) * 10000,
                    "bid": 0, "ask": 0, "bids": [], "asks": [],
                    "date": "", "time": "",
                }

    # ---- 个股 / ETF
    if stock_syms:
        txt = http_get("https://hq.sinajs.cn/list=" + ",".join(stock_syms), encoding="gbk")
        if txt:
            for m in _QUOTE_RE.finditer(txt):
                key = m.group(1)
                p = m.group(2).split(",")
                if len(p) < 32 or not p[0]:
                    continue
                price = _f(p[3]); prev = _f(p[2]); op = _f(p[1])
                if price <= 0:                        # 停牌用昨收兜底
                    price = prev
                chg = price - prev
                pct = (chg / prev * 100) if prev else 0.0
                bids, asks = [], []
                for i in range(5):
                    bv = _f(p[10 + i * 2]); bp = _f(p[11 + i * 2])
                    av = _f(p[20 + i * 2]); ap = _f(p[21 + i * 2])
                    if bp > 0:
                        bids.append({"price": bp, "volume": bv})
                    if ap > 0:
                        asks.append({"price": ap, "volume": av})
                out[key] = {
                    "symbol": key, "name": p[0],
                    "kind": "fund" if is_fund(key) else "stock",
                    "price": price, "change": round(chg, 4), "change_pct": round(pct, 3),
                    "prev_close": prev, "open": op,
                    "high": _f(p[4]), "low": _f(p[5]),
                    "volume": _f(p[8]), "amount": _f(p[9]),
                    "bid": _f(p[6]), "ask": _f(p[7]),
                    "bids": bids, "asks": asks,
                    "date": p[30] if len(p) > 30 else "",
                    "time": p[31] if len(p) > 31 else "",
                }

    # ---- 场外基金净值
    if fund_syms:
        txt = http_get("https://hq.sinajs.cn/list=" + ",".join(fund_syms), encoding="gbk")
        if txt:
            for m in _QUOTE_RE.finditer(txt):
                key = m.group(1)
                p = m.group(2).split(",")
                if len(p) < 6 or not p[0]:
                    continue
                nav = _f(p[1]); prev = _f(p[3]) or nav
                chg = nav - prev
                out[key] = {
                    "symbol": key, "name": p[0], "kind": "ofund",
                    "price": nav, "change": round(chg, 4),
                    "change_pct": round(chg / prev * 100, 3) if prev else 0.0,
                    "prev_close": prev, "open": nav, "high": nav, "low": nav,
                    "volume": 0, "amount": 0, "bid": 0, "ask": 0,
                    "bids": [], "asks": [],
                    "nav_acc": _f(p[2]), "scale": _f(p[5]),
                    "date": p[4] if len(p) > 4 else "", "time": "",
                }
    return out


# ------------------------------------------------------------------ K 线

def fetch_kline(symbol, scale=240, datalen=None):
    """
    scale: 5/15/30/60 分钟，240=日线，1200=周线，7200=月线
    返回 [{day, open, high, low, close, volume}]，按时间升序
    """
    if scale == 240:
        datalen = datalen or config.KLINE_LEN
    else:
        datalen = datalen or config.KLINE_LEN_MIN
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=%s&ma=no&datalen=%s"
           % (symbol, scale, datalen))
    txt = http_get(url, timeout=12)
    if not txt:
        return []
    txt = txt.strip()
    if not txt or txt in ("null", "[]"):
        return []
    try:
        rows = json.loads(txt)
    except Exception:
        # 新浪偶尔返回不带引号的 key，做一次修补
        try:
            fixed = re.sub(r"(\w+):", r'"\1":', txt)
            rows = json.loads(fixed)
        except Exception:
            return []
    bars = []
    for r in rows:
        try:
            bars.append({
                "day": r.get("day") or r.get("date") or "",
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume": float(r.get("volume") or 0),
            })
        except Exception:
            continue
    bars.sort(key=lambda b: b["day"])
    return bars


def fetch_kline_multi(symbol, scales):
    """并发拉多个周期的K线，返回 {scale: bars}"""
    out = {}
    with ThreadPoolExecutor(max_workers=min(config.CONCURRENCY, len(scales) or 1)) as ex:
        futs = {ex.submit(fetch_kline, symbol, sc): sc for sc in scales}
        for fu, sc in futs.items():
            try:
                out[sc] = fu.result()
            except Exception:
                out[sc] = []
    return out


# ------------------------------------------------------------------ 流通股本（算换手率）

_float_cache = {}
_float_lock = threading.Lock()


_TQ_RE = re.compile(r'v_(\w+)="([^"]*)"')


def fetch_tx_snapshot(symbols):
    """
    腾讯行情快照 —— 只用来补两个新浪不给的字段：换手率、流通市值。
    主行情仍然走新浪。返回 {symbol: {turnover, float_mv, total_mv, pe, pb}}
    """
    if not symbols:
        return {}
    txt = http_get("https://qt.gtimg.cn/q=" + ",".join(symbols),
                   encoding="gbk", timeout=8)
    out = {}
    if not txt:
        return out
    for m in _TQ_RE.finditer(txt):
        key = m.group(1)
        p = m.group(2).split("~")
        if len(p) < 46 or not p[1]:
            continue
        out[key] = {
            "name": p[1],
            "price": _f(p[3]),
            "turnover": _f(p[38]),
            "float_mv": _f(p[44]) * 1e8,      # 元
            "total_mv": _f(p[45]) * 1e8,
            "pe": _f(p[39]),
            "pb": _f(p[46]) if len(p) > 46 else 0.0,
            "amplitude": _f(p[43]),
        }
    return out


def fetch_float_shares(symbol):
    """
    流通股本（股）。用「流通市值 / 现价」反推。
    失败返回 0（下游自动退化为相对量能模型）。
    """
    with _float_lock:
        if symbol in _float_cache and _float_cache[symbol]:
            return _float_cache[symbol]
    val = 0.0
    if symbol.startswith(("sh", "sz", "bj")):
        snap = fetch_tx_snapshot([symbol]).get(symbol) or {}
        mv = snap.get("float_mv") or 0.0
        px = snap.get("price") or 0.0
        if mv > 0 and px > 0:
            val = mv / px
    with _float_lock:
        _float_cache[symbol] = val
    return val


def fetch_turnover(symbol):
    """当日换手率（%），来自腾讯快照。"""
    snap = fetch_tx_snapshot([symbol]).get(symbol) or {}
    return snap.get("turnover") or 0.0


# ------------------------------------------------------------------ 场外基金

def fetch_fund_nav_history(code, num=400):
    """
    场外基金历史净值。返回 [{day, nav, acc}] 升序。
    code 形如 110022（不带 f_）
    """
    body = code.replace("f_", "")
    url = ("https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/"
           "CaihuiFundInfoService.getNav?symbol=%s&datefrom=&dateto=&page=1&num=%d"
           % (body, num))
    txt = http_get(url, timeout=10)
    if not txt:
        return []
    try:
        d = json.loads(txt)
        rows = d["result"]["data"]["data"] or []
    except Exception:
        return []
    out = []
    for r in rows:
        try:
            out.append({
                "day": str(r.get("fbrq", ""))[:10],
                "nav": float(r.get("jjjz") or 0),
                "acc": float(r.get("ljjz") or 0),
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["day"])
    return out


def fetch_fund_info(code):
    """场外基金基本信息（全称、简称、成立日、经理、投资目标）"""
    body = code.replace("f_", "")
    url = ("https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/"
           "CaihuiFundInfoService.getFundInfo?symbol=%s" % body)
    txt = http_get(url, timeout=10)
    if not txt:
        return {}
    try:
        d = json.loads(txt)["result"]["data"] or {}
        return {
            "full_name": d.get("jjqc", ""),
            "short_name": d.get("jjjc", ""),
            "setup": str(d.get("clrq", ""))[:10],
            "manager": d.get("jjjl", ""),
            "target": d.get("tzmb", ""),
        }
    except Exception:
        return {}


# ------------------------------------------------------------------ 板块

_sector_cache = {"ts": 0, "data": []}
_sector_lock = threading.Lock()


def fetch_sectors(force=False):
    """新浪行业板块。返回 [{code,name,count,avg_price,change_pct,volume,amount,lead_symbol,lead_name}]"""
    with _sector_lock:
        if not force and time.time() - _sector_cache["ts"] < 60 and _sector_cache["data"]:
            return _sector_cache["data"]
    txt = http_get("https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
                   encoding="gbk", timeout=10)
    data = []
    if txt:
        i = txt.find("{")
        j = txt.rfind("}")
        if i >= 0 and j > i:
            try:
                obj = json.loads(txt[i:j + 1])
                for _, line in obj.items():
                    p = line.split(",")
                    if len(p) < 13:
                        continue
                    data.append({
                        "code": p[0], "name": p[1],
                        "count": int(_f(p[2])),
                        "avg_price": _f(p[3]),
                        "change": _f(p[4]),
                        "change_pct": _f(p[5]),
                        "volume": _f(p[6]),
                        "amount": _f(p[7]),
                        "lead_symbol": p[8], "lead_price": _f(p[9]),
                        "lead_change_pct": _f(p[10]),
                        "lead_change": _f(p[11]), "lead_name": p[12],
                    })
            except Exception:
                pass
    data.sort(key=lambda x: x["change_pct"], reverse=True)
    with _sector_lock:
        _sector_cache["ts"] = time.time()
        _sector_cache["data"] = data
    return data


# ------------------------------------------------------------------ 全市场列表（用于搜索/涨幅榜）

_node_cache = {}            # (node, sort, num) -> {"ts", "data"}
_node_lock = threading.Lock()
NODE_TTL = 20               # 列表缓存 20 秒


def fetch_market_list(num=200, sort="changepercent", node="hs_a"):
    """新浪全市场快照（含换手率、流通市值、市盈率）"""
    key = (node, sort, num)
    with _node_lock:
        item = _node_cache.get(key)
        if item and time.time() - item["ts"] < NODE_TTL:
            return item["data"]
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "Market_Center.getHQNodeData?page=1&num=%s&sort=%s&asc=0&node=%s&symbol=&_s_r_a=page"
           % (num, sort, node))
    txt = http_get(url, timeout=10)
    data = []
    if txt:
        try:
            data = json.loads(txt) or []
        except Exception:
            data = []
    with _node_lock:
        _node_cache[key] = {"ts": time.time(), "data": data}
        if len(_node_cache) > 30:
            oldest = min(_node_cache.items(), key=lambda kv: kv[1]["ts"])[0]
            _node_cache.pop(oldest, None)
    return data


# 场内基金列表 node（新浪）
FUND_NODES = {"etf": "etf_hq_fund", "lof": "lof_hq_fund"}


def fetch_fund_board(kind="etf", num=80, sort="changepercent"):
    """场内 ETF / LOF 列表"""
    node = FUND_NODES.get(kind, "etf_hq_fund")
    rows = fetch_market_list(num, sort, node)
    out = []
    for r in rows:
        try:
            out.append({
                "symbol": r.get("symbol", ""),
                "code": r.get("code", ""),
                "name": r.get("name", ""),
                "price": _f(r.get("trade")),
                "change": _f(r.get("pricechange")),
                "change_pct": _f(r.get("changepercent")),
                "volume": _f(r.get("volume")),
                "amount": _f(r.get("amount")),
                "turnover": _f(r.get("turnoverratio")),
                "kind": "fund",
            })
        except Exception:
            continue
    return out


def fetch_ofund_board(codes, sort="change_pct"):
    """场外基金列表（按代码批量查净值）"""
    syms = ["f_" + c for c in codes]
    quotes = fetch_quotes(syms)
    out = []
    for c in codes:
        q = quotes.get("f_" + c)
        if not q:
            continue
        out.append({
            "symbol": "f_" + c,
            "code": c,
            "name": q.get("name", c),
            "price": q.get("price", 0),
            "change": q.get("change", 0),
            "change_pct": q.get("change_pct", 0),
            "nav_acc": q.get("nav_acc", 0),
            "scale": q.get("scale", 0),
            "date": q.get("date", ""),
            "kind": "ofund",
        })
    if sort == "change_pct":
        out.sort(key=lambda x: -x["change_pct"])
    return out


def force_stale(cache, ttl=45):
    return time.time() - cache["ts"] > ttl


# ------------------------------------------------------------------ 名称检索

_SUGGEST_RE = re.compile(r'suggestvalue="([^"]*)"')


def search_symbol(q, limit=12):
    """
    按代码或名称/拼音检索。返回 [{'symbol','code','name','kind'}]
    纯 6 位数字直接查行情；其它走新浪 suggest 接口。
    """
    q = (q or "").strip()
    if not q:
        return []
    out = []
    if q.isdigit() and len(q) == 6:
        sym = normalize_code(q)
        if sym:
            quote = fetch_quotes([sym]).get(sym)
            if quote:
                out.append({"symbol": sym, "code": q, "name": quote.get("name", q),
                            "kind": quote.get("kind", "stock")})
        if not out:
            fq = fetch_quotes(["f_" + q]).get("f_" + q)
            if fq:
                out.append({"symbol": "f_" + q, "code": q, "name": fq.get("name", q),
                            "kind": "ofund"})
        return out

    url = ("https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15,21,22,23,24,25,26,"
           "31,33,41&key=" + urllib.parse.quote(q))
    txt = http_get(url, encoding="gbk", timeout=6)
    if txt:
        m = _SUGGEST_RE.search(txt)
        if m and m.group(1):
            for item in m.group(1).split(";"):
                p = item.split(",")
                if len(p) < 5:
                    continue
                sym = p[3]
                if not sym or not re.match(r"^(sh|sz|bj)\d{6}$", sym):
                    continue
                out.append({"symbol": sym, "code": sym[2:], "name": p[0],
                            "kind": "fund" if is_fund(sym) else "stock"})
    seen = set()
    uniq = []
    for x in out:
        if x["symbol"] in seen:
            continue
        seen.add(x["symbol"])
        uniq.append(x)
    return uniq[:limit]


def resolve(raw):
    """把用户输入（代码 / 名称）解析成 symbol。失败返回 None。"""
    sym = normalize_code(raw)
    if sym:
        return sym
    items = search_symbol(raw, 1)
    return items[0]["symbol"] if items else None


def guess_name(symbol):
    q = fetch_quotes([symbol])
    return (q.get(symbol) or {}).get("name") or symbol


# ================================================================== 外围市场
#
# 新浪对不同市场的字段顺序完全不一样，这里按前缀分别解析：
#   int_xxx   全球指数     名称, 价, 涨跌额, 涨跌幅
#   gb_xxx    美股         名称, 价, 涨跌幅%, 时间, 涨跌额, 开, 高, 低, 52高, 52低, 量, ...
#   rt_hkXXX  港股指数     代码, 名称, 开, 昨收, 高, 低, 价, 涨跌额, 涨跌幅, ..., 52高, 52低, 日期, 时间
#   hkXXXXX   港股个股     同上
#   fx_sXXX   外汇         时间, 买, 卖, 昨收, ?, 开, 高, 低, 价, 名称, 涨跌幅, 涨跌额, ..., 52高, 52低, ?, 日期
#   hf_XXX    国际期货     价, ?, 买, 卖, 高, 低, 时间, 昨收, 开, ..., 日期, 名称, ?
#   nf_XXX    国内期货     名称, 时间, 开, 高, 低, ?, 买, 卖, 价, ?, 结算, ...

def _parse_global(key, p):
    """解析单条外围行情。返回统一结构，字段缺失时给 None。"""
    def g(i, d=None):
        return p[i] if i < len(p) else d

    out = {"symbol": key, "raw_len": len(p)}
    if key.startswith("gb_"):
        out.update({
            "name": g(0, key), "price": _f(g(1)), "change_pct": _f(g(2)),
            "time": g(3, ""), "change": _f(g(4)), "open": _f(g(5)),
            "high": _f(g(6)), "low": _f(g(7)),
            "w52_high": _f(g(8)), "w52_low": _f(g(9)), "volume": _f(g(10)),
            "market": "US", "currency": "USD",
        })
        out["prev_close"] = out["price"] - out["change"] if out["change"] else 0.0
    elif key.startswith("rt_hk") or key.startswith("hk"):
        out.update({
            "name": g(1, key), "open": _f(g(2)), "prev_close": _f(g(3)),
            "high": _f(g(4)), "low": _f(g(5)), "price": _f(g(6)),
            "change": _f(g(7)), "change_pct": _f(g(8)),
            "amount": _f(g(11)), "volume": _f(g(12)),
            "w52_high": _f(g(15)), "w52_low": _f(g(16)),
            "date": g(17, ""), "time": g(18, ""),
            "market": "HK", "currency": "HKD",
        })
    elif key.startswith("int_"):
        price, chg = _f(g(1)), _f(g(2))
        out.update({
            "name": g(0, key), "price": price, "change": chg,
            "change_pct": _f(g(3)), "prev_close": price - chg,
            "open": 0.0, "high": 0.0, "low": 0.0,
            "w52_high": 0.0, "w52_low": 0.0, "volume": 0.0,
            "market": "GL", "currency": "",
        })
    elif key.startswith("fx_s"):
        price = _f(g(8))
        prev = _f(g(3))
        out.update({
            "name": g(9, key), "price": price, "open": _f(g(5)),
            "high": _f(g(6)), "low": _f(g(7)), "prev_close": prev,
            "change_pct": _f(g(10)), "change": _f(g(11)),
            "w52_high": _f(g(14)), "w52_low": _f(g(15)),
            "time": g(0, ""), "date": g(17, ""),
            "market": "FX", "currency": "",
        })
        if not out["change"] and prev:
            out["change"] = price - prev
            out["change_pct"] = out["change"] / prev * 100
    elif key.startswith("hf_"):
        price = _f(g(0))
        prev = _f(g(7))
        out.update({
            "name": g(13, key), "price": price, "open": _f(g(8)),
            "high": _f(g(4)), "low": _f(g(5)), "prev_close": prev,
            "change": price - prev if prev else 0.0,
            "change_pct": (price - prev) / prev * 100 if prev else 0.0,
            "w52_high": 0.0, "w52_low": 0.0,
            "time": g(6, ""), "date": g(12, ""),
            "market": "CM", "currency": "USD",
        })
    elif key.startswith("nf_"):
        price = _f(g(8))
        op = _f(g(2))
        out.update({
            "name": g(0, key), "open": op, "high": _f(g(3)), "low": _f(g(4)),
            "price": price, "prev_close": op,
            "change": price - op if op else 0.0,
            "change_pct": (price - op) / op * 100 if op else 0.0,
            "w52_high": 0.0, "w52_low": 0.0,
            "volume": _f(g(14)), "time": g(1, ""), "date": g(17, ""),
            "market": "CN", "currency": "CNY",
        })
    else:
        return None

    # 位置分位（0 底部 / 1 顶部），没有 52 周数据时用当日高低
    hi = out.get("w52_high") or out.get("high") or 0
    lo = out.get("w52_low") or out.get("low") or 0
    px = out.get("price") or 0
    out["pos52"] = round((px - lo) / (hi - lo) * 100, 1) if hi > lo else None
    d_hi, d_lo = out.get("high") or 0, out.get("low") or 0
    out["pos_day"] = round((px - d_lo) / (d_hi - d_lo) * 100, 1) if d_hi > d_lo else None
    out["kind"] = "global"
    return out


def fetch_global(keys):
    """批量拉外围行情，返回 {key: dict}"""
    if not keys:
        return {}
    out = {}
    for i in range(0, len(keys), 30):
        batch = keys[i:i + 30]
        txt = http_get("https://hq.sinajs.cn/list=" + ",".join(batch), encoding="gbk")
        if not txt:
            continue
        for m in _QUOTE_RE.finditer(txt):
            key, raw = m.group(1), m.group(2)
            if not raw:
                continue
            try:
                d = _parse_global(key, raw.split(","))
            except Exception:
                d = None
            if d and d.get("price"):
                out[key] = d
    return out


_JSONP_RE = re.compile(r"=\s*(\[.*\]|\{.*\})\s*;?\s*$", re.S)


def _jsonp_payload(txt):
    """
    剥离新浪的 JSONP 外壳：
        /*<script>...</script>*/ var _k=([{"a":1}]);   →   [{"a":1}]
    """
    if not txt:
        return None
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S).strip()
    i = txt.find("=")
    if i < 0:
        return None
    body = txt[i + 1:].strip()
    while body and body[-1] in ";\r\n\t ":
        body = body[:-1].strip()
    # 去掉外层包裹的圆括号  ([...])  /  ({...})
    if len(body) >= 2 and body[0] == "(" and body[-1] == ")":
        body = body[1:-1].strip()
    if not body or body[0] not in "[{":
        m = re.search(r"[\[{].*[\]}]", body, re.S)
        if not m:
            return None
        body = m.group(0)
    try:
        return json.loads(body)
    except Exception:
        return None


def fetch_us_kline(symbol, length=None):
    """
    美股日线。symbol 形如 gb_aapl / gb_$dji。
    新浪返回的是全历史（可能上万条），这里截取尾部。
    """
    length = length or config.US_KLINE_LEN
    # 个股用代码（AAPL），指数用带点的形式（.DJI / .IXIC / .INX）
    body = config.US_KLINE_MAP.get(symbol) or (
        symbol[3:] if symbol.startswith("gb_") else symbol)
    url = ("https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20_k=/"
           "US_MinKService.getDailyK?symbol=" + body + "&___qn=3")
    txt = http_get(url, timeout=15)
    rows = _jsonp_payload(txt)
    if not isinstance(rows, list):
        return []
    bars = []
    for r in rows[-length:]:
        try:
            bars.append({
                "day": str(r.get("d", "")),
                "open": float(r["o"]), "high": float(r["h"]),
                "low": float(r["l"]), "close": float(r["c"]),
                "volume": float(r.get("v") or 0),
            })
        except Exception:
            continue
    bars.sort(key=lambda b: b["day"])
    return bars


def fetch_hk_kline(symbol, length=None):
    """
    港股日线 —— 新浪没有港股日K接口，用「多日分时」聚合成日K。
    symbol 形如 hk00700 / rt_hkHSI。
    """
    length = length or 30
    code = symbol.replace("rt_", "")
    body = code[2:] if code.startswith("hk") else code
    url = ("https://quotes.sina.cn/hk/api/openapi.php/"
           "HK_MinlineService.getMinline?symbol=%s" % body)
    txt = http_get(url, timeout=12)
    if not txt:
        return []
    try:
        days = json.loads(txt)["result"]["data"]
    except Exception:
        return []
    bars = []
    for day in days or []:
        if not day:
            continue
        try:
            d = day[0].get("date", "")
            prices = [float(x["price"]) for x in day if x.get("price")]
            vols = [float(x.get("volume") or 0) for x in day]
            if not prices:
                continue
            bars.append({
                "day": d, "open": prices[0], "high": max(prices),
                "low": min(prices), "close": prices[-1],
                "volume": sum(vols),
            })
        except Exception:
            continue
    bars.sort(key=lambda b: b["day"])
    return bars[-length:]


def fetch_futures_kline(symbol, length=None):
    """国际期货日线。symbol 形如 hf_GC。"""
    length = length or config.FUT_KLINE_LEN
    code = config.FUT_KLINE_MAP.get(symbol)
    if not code:
        return []
    url = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_k=/"
           "GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=" + code +
           "&_=" + str(int(time.time())))
    txt = http_get(url, timeout=15)
    rows = _jsonp_payload(txt)
    if not isinstance(rows, list):
        return []
    bars = []
    for r in rows[-length:]:
        try:
            bars.append({
                "day": str(r.get("date", "")),
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume": float(r.get("volume") or 0),
            })
        except Exception:
            continue
    bars.sort(key=lambda b: b["day"])
    return bars


def fetch_global_kline(symbol, length=None):
    """按标的前缀自动选择 K 线来源。"""
    if symbol.startswith("gb_"):
        return fetch_us_kline(symbol, length)
    if symbol.startswith("rt_hk") or symbol.startswith("hk"):
        return fetch_hk_kline(symbol, length)
    if symbol.startswith("hf_"):
        return fetch_futures_kline(symbol, length)
    return []
