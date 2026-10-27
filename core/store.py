# -*- coding: utf-8 -*-
"""
数据中枢 · store.py
===================
职责：
  1. 后台轮询线程，严格按 config.POLL_INTERVAL（20s）抓取外部数据；
  2. 分析结果缓存（TTL 与轮询周期一致）；
  3. 自选股持久化；
  4. 控制台实时日志（这是「终端」那一半）。

前端只读缓存，不会触发外部请求 —— 这样无论开几个页面，
对新浪的请求频率都恒定在 20 秒一次。
"""

import json
import os
import threading
import time
import datetime

from . import config
from . import sina
from . import engine
from . import global_market

C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_GRAY = "\033[90m"
C_CYAN = "\033[96m"
C_YELLOW = "\033[93m"
C_BOLD = "\033[1m"
C_END = "\033[0m"


def _color(txt, c):
    if not config.LOG_COLOR:
        return txt
    return c + txt + C_END


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.cache = {}          # (symbol, scale) -> {"ts": float, "data": dict}
        self.quotes = {}         # symbol -> quote
        self.watch = self._load_watch()
        self.current = None      # {"symbol":..., "scale":...}
        self.wake = threading.Event()
        self.running = False
        self.stats = {
            "rounds": 0, "last_poll": 0.0, "last_ms": 0, "next_at": 0.0,
            "errors": 0, "started": time.time(), "log": [],
        }
        self.index_codes = ["sh000001", "sz399001", "sz399006", "sh000688"]
        self.indices = {}
        self.global_data = {}
        self.stats["global_ts"] = 0.0

    # -------------------------------------------------- 自选
    def _load_watch(self):
        try:
            if os.path.exists(config.WATCHLIST_FILE):
                with open(config.WATCHLIST_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return [sina.normalize_code(x) for x in data if sina.normalize_code(x)]
        except Exception:
            pass
        return ["sh600519", "sz000001", "sh510300", "sz159915", "sh601318"]

    def _save_watch(self):
        try:
            with open(config.WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(self.watch, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def add_watch(self, symbol):
        symbol = sina.normalize_code(symbol) or sina.resolve(symbol)
        if symbol and symbol not in self.watch:
            self.watch.append(symbol)
            self._save_watch()
        return self.watch

    def remove_watch(self, symbol):
        symbol = sina.normalize_code(symbol)
        if symbol in self.watch:
            self.watch.remove(symbol)
            self._save_watch()
        return self.watch

    # -------------------------------------------------- 当前标的
    def set_current(self, symbol, scale=240):
        symbol = sina.normalize_code(symbol) or sina.resolve(symbol)
        if not symbol:
            return self.current
        with self.lock:
            changed = (not self.current) or self.current["symbol"] != symbol \
                      or self.current["scale"] != scale
            self.current = {"symbol": symbol, "scale": scale}
        if changed:
            self.wake.set()
        return self.current

    # -------------------------------------------------- 读取
    def get_analysis(self, symbol, scale=240, allow_sync=True):
        symbol = sina.normalize_code(symbol)
        key = (symbol, scale)
        now = time.time()
        with self.lock:
            item = self.cache.get(key)
            if item and now - item["ts"] < config.POLL_INTERVAL:
                return item["data"]
        if not allow_sync:
            return None
        return self._refresh_one(symbol, scale, force=True)

    def _refresh_one(self, symbol, scale, force=False):
        key = (symbol, scale)
        now = time.time()
        if not force:
            with self.lock:
                item = self.cache.get(key)
                if item and now - item["ts"] < config.POLL_DEEP:
                    return item["data"]
        t0 = time.time()
        try:
            data = engine.analyze(symbol, scale)
        except Exception as e:                          # noqa: BLE001
            self.stats["errors"] += 1
            data = {"ok": False, "symbol": symbol, "reason": "分析异常：%s" % e}
        ms = int((time.time() - t0) * 1000)
        with self.lock:
            self.cache[key] = {"ts": time.time(), "data": data}
            if data.get("ok") and data.get("quote"):
                self.quotes[symbol] = data["quote"]
        return data

    def _patch_quote(self, data, quote):
        """深度分析 30s 才算一次，但行情 5s 一跳 —— 把最新价刷进缓存结果。"""
        if not data or not data.get("ok") or not quote:
            return
        try:
            data["quote"] = quote
            data["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            view = data.get("view") or {}
            bars = view.get("bars") or []
            if bars:
                last = bars[-1]
                px = quote.get("price") or 0
                if px > 0 and last.get("d") == quote.get("date"):
                    last["c"] = round(px, 3)
                    if px > (last.get("h") or 0):
                        last["h"] = round(px, 3)
                    if px < (last.get("l") or 99999999):
                        last["l"] = round(px, 3)
        except Exception:
            pass

    # -------------------------------------------------- 日志
    def log(self, text):
        line = "[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), text)
        self.stats["log"].append(line)
        if len(self.stats["log"]) > 200:
            self.stats["log"] = self.stats["log"][-200:]
        try:
            print(line, flush=True)
        except Exception:
            pass

    def _log_analysis(self, d):
        if not d or not d.get("ok"):
            return
        q = d.get("quote") or {}
        a = d.get("analysis") or {}
        sc = (a.get("score") or {}).get("score", 0)
        lv = (a.get("score") or {}).get("level", {}).get("name", "")
        cp = a.get("chip") or {}
        ph = (a.get("phase") or {}).get("phase", "")
        pct = q.get("change_pct", 0)
        pc = _color("%+.2f%%" % pct, C_RED if pct >= 0 else C_GREEN)
        sc_c = C_RED if sc >= 0 else C_GREEN
        parts = [
            _color("#%03d" % self.stats["rounds"], C_GRAY),
            _color("%-6s" % (d.get("name") or ""), C_BOLD),
            _color(d.get("symbol", ""), C_GRAY),
            "%-10s" % ("%.3f" % q.get("price", 0)),
            "%9s" % pc,
            "| 评分 %s" % _color("%+.1f" % sc, sc_c),
            _color(lv, sc_c),
        ]
        if cp:
            parts.append("| 主力成本 %.2f 控盘 %.0f%% 获利 %.0f%%" %
                         (cp.get("main_cost", 0), cp.get("control", 0),
                          cp.get("profit_ratio", 0)))
        if ph:
            parts.append("| %s" % ph)
        parts.append(_color("%dms" % self.stats["last_ms"], C_GRAY))
        self.log(" ".join(parts))

    # -------------------------------------------------- 轮询
    def _fetch_watch_quotes(self):
        """自选股行情（A 股 + 外围分开拉）"""
        a_syms = [s for s in self.watch if not sina.is_global(s)]
        g_syms = [s for s in self.watch if sina.is_global(s)]
        out = {}
        if a_syms:
            try:
                out.update(sina.fetch_quotes(a_syms))
            except Exception:
                pass
        if g_syms:
            try:
                out.update(sina.fetch_global(g_syms))
            except Exception:
                pass
        return out

    def _log_tick(self, d):
        """深度分析未重算的那几轮，只打印行情跳动，保持控制台 5 秒一行。"""
        if not d or not d.get("ok"):
            return
        q = d.get("quote") or {}
        pct = q.get("change_pct", 0)
        pc = _color("%+.2f%%" % pct, C_RED if pct >= 0 else C_GREEN)
        sc = ((d.get("analysis") or {}).get("score") or {}).get("score", 0)
        sc_c = C_RED if sc >= 0 else C_GREEN
        self.log(" ".join([
            _color("#%03d" % self.stats["rounds"], C_GRAY),
            _color("%-6s" % (d.get("name") or ""), C_BOLD),
            _color(d.get("symbol", ""), C_GRAY),
            "%-10s" % ("%.3f" % (q.get("price") or 0)),
            "%9s" % pc,
            _color("·", C_GRAY),
            "评分 %s" % _color("%+.1f" % sc, sc_c),
            _color("行情刷新", C_GRAY),
        ]))

    def _poll_once(self):
        t0 = time.time()
        self.stats["rounds"] += 1

        # 指数
        try:
            idx = sina.fetch_quotes(self.index_codes)
            with self.lock:
                self.indices = idx
                self.quotes.update(idx)
        except Exception:
            pass

        # 自选股行情（A 股 + 外围，一次批量）
        try:
            wq = self._fetch_watch_quotes()
            with self.lock:
                self.quotes.update(wq)
        except Exception:
            pass

        # 外围市场总览（每 5 秒）
        try:
            self.global_data = global_market.snapshot()
            self.stats["global_ts"] = time.time()
        except Exception:
            pass

        # 当前标的
        cur = self.current
        if cur and cur["symbol"]:
            key = (cur["symbol"], cur["scale"])
            with self.lock:
                item = self.cache.get(key)
            need_deep = (item is None) or \
                (time.time() - item["ts"] > config.POLL_DEEP)
            if need_deep:
                d = self._refresh_one(cur["symbol"], cur["scale"], force=True)
                self.stats["last_ms"] = int((time.time() - t0) * 1000)
                self._log_analysis(d)
            else:
                # 只刷行情，分析结果保留
                q = self.quotes.get(cur["symbol"])
                if q and item:
                    self._patch_quote(item["data"], q)
                self.stats["last_ms"] = int((time.time() - t0) * 1000)
                self._log_tick(item["data"] if item else None)
        else:
            self.stats["last_ms"] = int((time.time() - t0) * 1000)
            self.log("轮询 %d 个自选股行情" % len(self.watch))

        self.stats["last_poll"] = time.time()
        self.stats["next_at"] = time.time() + config.POLL_INTERVAL

    def poll_loop(self):
        self.running = True
        while self.running:
            try:
                self._poll_once()
            except Exception as e:                      # noqa: BLE001
                self.stats["errors"] += 1
                self.log(_color("轮询异常：%s" % e, C_RED))
            # 等待下一个周期，或被 set_current 唤醒
            waited = 0.0
            while waited < config.POLL_INTERVAL:
                if self.wake.wait(timeout=0.5):
                    self.wake.clear()
                    break
                waited += 0.5

    def start(self):
        t = threading.Thread(target=self.poll_loop, daemon=True, name="poller")
        t.start()
        return t

    # -------------------------------------------------- 状态
    def status(self):
        now = time.time()
        gd = self.global_data or {}
        return {
            "running": self.running,
            "interval": config.POLL_INTERVAL,
            "deep_interval": config.POLL_DEEP,
            "rounds": self.stats["rounds"],
            "last_poll": self.stats["last_poll"],
            "last_poll_str": datetime.datetime.fromtimestamp(
                self.stats["last_poll"]).strftime("%H:%M:%S") if self.stats["last_poll"] else "--",
            "next_in": max(0, round(self.stats["next_at"] - now, 1)),
            "last_ms": self.stats["last_ms"],
            "errors": self.stats["errors"],
            "uptime": int(now - self.stats["started"]),
            "cache_size": len(self.cache),
            "watch": self.watch,
            "current": self.current,
            "log": self.stats["log"][-40:],
            "indices": self.indices,
            "global": {
                "risk": gd.get("risk") or {},
                "total": gd.get("total", 0),
                "ts": self.stats.get("global_ts", 0),
            },
        }


store = Store()
