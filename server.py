# -*- coding: utf-8 -*-
"""
交易很轻松 · 本地服务
=====================
纯标准库 HTTP 服务（ThreadingHTTPServer），零第三方依赖。
启动后：控制台持续打印 20s 一轮的抓取日志，浏览器自动打开新浪财经风格的界面。
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import threading
import webbrowser
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core import config, sina, store as store_mod, engine, global_market, sectors
else:
    from .core import config, sina, store as store_mod, engine, global_market, sectors

STORE = store_mod.store


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if v == v else d
    except Exception:
        return d

BANNER = r"""
   ______                __     __         __                                
  /_  __/________ ______/ /_   / /  ___   / /_____  ____  ____  __  __
   / / / ___/ __ `/ ___/ __/  / /  / _ \ / __/ __ \/ __ \/ __ \/ / / /
  / / / /  / /_/ / /  / /_   / /__/  __// /_/ /_/ / /_/ / /_/ / /_/ /
 /_/ /_/   \__,_/_/   \__/  /____/\___/ \__/\____/\____/\____/\__, /
                                                             /____/
  交易很轻松  ·  新浪财经数据 + 缠论 + 筹码分布 + 主力行为识别
"""


def _probe(url, timeout=0.6):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "probe"})
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return op.open(req, timeout=timeout).read().decode("utf-8", "replace")
    except Exception:
        return None


def lan_ips():
    """本机在局域网里的 IPv4 地址（不发实际数据包，只查路由表）"""
    ips = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        ips.append(s.getsockname()[0])
    except Exception:
        pass
    finally:
        s.close()
    # 多网卡（虚拟机 / 有线 + 无线）时把其它地址也列出来
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.append(ip)
    except Exception:
        pass
    return ips


def is_termux():
    """是否跑在安卓 Termux 里"""
    if "com.termux" in os.environ.get("PREFIX", ""):
        return True
    return shutil.which("termux-open-url") is not None


def open_url(url):
    """打开浏览器：Termux 里交给 termux-open-url，电脑上走 webbrowser"""
    if shutil.which("termux-open-url"):
        try:
            subprocess.Popen(["termux-open-url", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def print_access(port):
    """打印访问地址（区分「电脑当服务器」和「手机自己跑」两种场景）"""
    print("  " + "-" * 66)
    if is_termux():
        print("  在手机浏览器打开：http://%s:%d/" % (config.LOCAL_HOST, port))
        ips = lan_ips()
        if ips:
            print("  别的设备访问：http://%s:%d/    （同一 WiFi）" % (ips[0], port))
        print("  提示：别让 Termux 被系统清掉 —— 电池优化里给 Termux 设为「不限制」")
        print("  " + "-" * 66)
        return
    print("  本机访问：http://%s:%d/" % (config.LOCAL_HOST, port))
    if config.SERVER_HOST == "0.0.0.0":
        ips = lan_ips()
        if ips:
            print("  手机访问：http://%s:%d/    （手机连同一个 WiFi）" % (ips[0], port))
            for ip in ips[1:]:
                print("  其它网卡：http://%s:%d/    （多网卡时可换这个试）" % (ip, port))
            if sys.platform == "win32":
                print("  提示：手机打不开 → 检查 Windows 防火墙是否放行 python（专用网络）")
        else:
            print("  手机访问：未取到局域网 IP，确认电脑已连上 WiFi / 网线")
    else:
        print("  当前仅监听 %s，手机无法访问（设 JYHQS_HOST=0.0.0.0 可开放局域网）"
              % config.SERVER_HOST)
    print("  " + "-" * 66)


def port_busy(port, timeout=0.3):
    """端口上是否已经有人在听（纯 socket，不走代理，通常 <30ms）"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def find_running(port, scan=None):
    """检查是否已有本服务在跑（避免重复启动导致端口冲突）"""
    scan = scan or config.PORT_SCAN
    for i in range(scan):
        p = port + i
        txt = _probe("http://127.0.0.1:%d/api/status" % p)
        if txt and '"running"' in txt:
            return p
    return None


def bind_server(handler, host, port):
    """端口被占用时自动向后寻找可用端口"""
    last = None
    for i in range(config.PORT_SCAN):
        p = port + i
        try:
            srv = ThreadingHTTPServer((host, p), handler)
            srv.daemon_threads = True
            return srv, p
        except OSError as e:
            last = e
            continue
    raise RuntimeError("端口 %d~%d 全部被占用：%s"
                       % (port, port + config.PORT_SCAN - 1, last))


# ------------------------------------------------------------ 搜索

def search(q):
    return sina.search_symbol(q, 12)


# ------------------------------------------------------------ HTTP

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "JiaoYiHenQingSong/1.0"

    def log_message(self, fmt, *args):        # 静音默认访问日志
        pass

    def handle_one_request(self):
        """手机在弱网下随时可能断开，别让 ConnectionReset 刷屏控制台"""
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    # ---------------- 工具
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str)
        data = body.encode("utf-8") if isinstance(body, str) else body
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def _json(self, obj, code=200):
        self._send(code, obj)

    def _file(self, path):
        if not os.path.isfile(path):
            self._send(404, "404 Not Found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(path)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception:
            self._send(500, "read error", "text/plain")
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    # ---------------- 路由
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        def g(k, d=None):
            v = qs.get(k)
            return v[0] if v else d

        try:
            if path in ("/", "/index.html"):
                return self._file(os.path.join(config.WEB_DIR, "index.html"))

            if path.startswith("/static/"):
                name = path[len("/static/"):]
                if ".." in name or name.startswith("/"):
                    return self._send(403, "forbidden", "text/plain")
                return self._file(os.path.join(config.WEB_DIR, name))

            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")

            if path == "/api/status":
                return self._json(STORE.status())

            if path == "/api/snapshot":
                raw = g("code")
                scale = int(g("scale", "240"))
                if not raw:
                    return self._json({"ok": False, "reason": "缺少 code 参数"}, 400)
                code = sina.normalize_code(raw) or sina.resolve(raw)
                if not code:
                    return self._json({"ok": False, "reason": "无法识别：%s" % raw})
                STORE.set_current(code, scale)
                data = STORE.get_analysis(code, scale)
                return self._json(data)

            if path == "/api/search":
                q = g("q", "")
                items = sina.search_symbol(q, 8)
                # 外围市场也参与检索
                g_items = global_market.match(q)
                seen = {x["symbol"] for x in items}
                items.extend(x for x in g_items if x["symbol"] not in seen)
                return self._json({"ok": True, "items": items[:14]})

            if path == "/api/global":
                if not STORE.global_data or \
                        time.time() - STORE.stats.get("global_ts", 0) > config.POLL_INTERVAL * 2:
                    STORE.global_data = global_market.snapshot()
                    STORE.stats["global_ts"] = time.time()
                return self._json(STORE.global_data)

            if path == "/api/global/one":
                key = g("code", "")
                if not key:
                    return self._json({"ok": False, "reason": "缺少 code"}, 400)
                return self._json(global_market.analyze(key))

            if path == "/api/sectors":
                return self._json({"ok": True, "items": sina.fetch_sectors()})

            # ---- 板块成分股
            if path == "/api/board":
                code = g("code", "")
                return self._json(sectors.board_stocks(code, 200))

            # ---- 统一列表接口（导航栏四个页签都走这里）
            if path == "/api/list":
                kind = g("type", "stock")
                sort = g("sort", "changepercent")
                num = int(g("num", "60"))
                if kind == "sector":
                    theme = g("theme", "")
                    sd = sectors.by_theme(theme or None, None, sort, num)
                    items = sd["items"]
                    sub = "%d 个板块 · %d 个主题" % (sd["total"], len(sd["themes"]))
                    if theme:
                        sub = "%s · %d 个细分板块" % (theme, sd["total"])
                    return self._json({
                        "ok": True, "type": kind, "title": "板块",
                        "subtitle": sub,
                        "themes": sd["themes"],
                        "source": sd["source"],
                        "items": [{
                            "symbol": b["lead_code"],
                            "code": b["code"],
                            "name": b["name"],
                            "price": 0,
                            "amount_yi": round(b["amount"] / 1e8, 1) if b.get("amount") else 0,
                            "change": round(b["change_pct"], 2),
                            "change_pct": round(b["change_pct"], 2),
                            "theme": b.get("theme", ""),
                            "kind": "sector",
                            "extra": ("%d只 · " % b["count"] if b.get("count") else "") +
                                     "领涨 " + b["lead_name"] +
                                     " %+.2f%%" % b["lead_pct"],
                        } for b in items],
                    })
                if kind in ("etf", "lof"):
                    items = sina.fetch_fund_board(kind, num, sort)
                    title = "场内 ETF" if kind == "etf" else "场内 LOF"
                    return self._json({
                        "ok": True, "type": kind, "title": title,
                        "subtitle": "%d 只 · 按%s排序" % (len(items), "涨跌幅" if sort == "changepercent" else sort),
                        "items": [{
                            "symbol": it["symbol"], "code": it["code"], "name": it["name"],
                            "price": it["price"], "change": it["change"],
                            "change_pct": it["change_pct"],
                            "extra": "换手 %.2f%% · 额 %.2f亿" % (it["turnover"], it["amount"] / 1e8),
                            "kind": "fund",
                        } for it in items],
                    })
                if kind == "ofund":
                    items = sina.fetch_ofund_board(config.OFUND_SEED, "change_pct")[:num]
                    return self._json({
                        "ok": True, "type": kind, "title": "场外基金",
                        "subtitle": "%d 只 · 常见宽基与主动权益（按当日净值涨幅）" % len(items),
                        "items": [{
                            "symbol": it["symbol"], "code": it["code"], "name": it["name"],
                            "price": it["price"], "change": it["change"],
                            "change_pct": it["change_pct"],
                            "extra": "净值 %s · 规模 %s亿" % (it["date"], ("%.1f" % it["scale"]) if it["scale"] else "—"),
                            "kind": "ofund",
                        } for it in items],
                    })
                # 个股（全市场）
                rows = sina.fetch_market_list(num, sort, "hs_a")
                smap = {"changepercent": "涨跌幅", "turnoverratio": "换手率",
                        "amount": "成交额", "volume": "成交量", "trade": "价格"}
                items = []
                for r in rows:
                    try:
                        items.append({
                            "symbol": r["symbol"], "code": r["code"], "name": r["name"],
                            "price": _f(r.get("trade")),
                            "change": _f(r.get("pricechange")),
                            "change_pct": _f(r.get("changepercent")),
                            "extra": "换手 %.2f%% · 额 %.2f亿 · PE %.1f" % (
                                _f(r.get("turnoverratio")), _f(r.get("amount")) / 1e8, _f(r.get("per"))),
                            "kind": "stock",
                        })
                    except Exception:
                        continue
                return self._json({
                    "ok": True, "type": "stock", "title": "个股",
                    "subtitle": "%d 只 A 股 · 按%s降序" % (len(items), smap.get(sort, sort)),
                    "items": items,
                })

            if path == "/api/rank":
                node = g("node", "hs_a")
                sort = g("sort", "changepercent")
                num = int(g("num", "20"))
                rows = sina.fetch_market_list(num, sort, node)
                return self._json({"ok": True, "items": rows})

            if path == "/api/watch":
                action = g("action")
                code = g("code")
                if action == "add" and code:
                    STORE.add_watch(code)
                    STORE.wake.set()
                elif action == "remove" and code:
                    STORE.remove_watch(code)
                quotes = sina.fetch_quotes(STORE.watch) if STORE.watch else {}
                return self._json({"ok": True, "watch": STORE.watch, "quotes": quotes})

            if path == "/api/indices":
                return self._json({"ok": True, "items": sina.fetch_quotes(STORE.index_codes)})

            if path == "/api/kline":
                code = sina.normalize_code(g("code", ""))
                scale = int(g("scale", "240"))
                ln = int(g("len", "300"))
                bars = sina.fetch_kline(code, scale, ln)
                return self._json({"ok": True, "bars": bars})

            return self._send(404, "404 Not Found", "text/plain; charset=utf-8")
        except Exception as e:                       # noqa: BLE001
            return self._json({"ok": False, "reason": "服务端异常：%s" % e}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/watch":
            try:
                ln = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(ln) or b"{}")
            except Exception:
                body = {}
            action = body.get("action")
            code = body.get("code")
            if action == "add" and code:
                STORE.add_watch(code)
                STORE.wake.set()
            elif action == "remove" and code:
                STORE.remove_watch(code)
            return self._json({"ok": True, "watch": STORE.watch})
        return self._json({"ok": False, "reason": "not found"}, 404)


def main():
    config.enable_utf8_console()
    print(BANNER)

    print("  数据源：新浪财经（A股 / 场内ETF·LOF / 场外基金 / 外围市场）")
    print("  指标库：兼容 pandas-ta 命名 · 缠论 · CYQ 筹码 · 威科夫主力阶段")
    print("  基金：主动 / 被动分离评价（跟踪误差 vs Alpha·信息比率）")
    print("  " + "-" * 66)

    STORE.set_current(STORE.watch[0] if STORE.watch else "sh600519", 240)

    # ---- 先探一次端口：没人听就直接绑（Windows 上 SO_REUSEADDR 允许重复绑同一端口，
    #      所以不能「先绑再判断」，必须先探测）
    httpd = None
    port = config.SERVER_PORT
    if not port_busy(port):
        try:
            httpd = ThreadingHTTPServer((config.SERVER_HOST, port), Handler)
            httpd.daemon_threads = True
        except OSError as e:
            print("  [错误] 端口 %d 绑定失败：%s" % (port, e))
            return
    if httpd is None:
        # 端口有人占用：先确认是不是本服务已经在跑
        running = find_running(config.SERVER_PORT, scan=3)
        if running:
            print("  检测到服务已在运行，直接打开浏览器即可。")
            print_access(running)
            if config.AUTO_OPEN_BROWSER:
                open_url("http://%s:%d/" % (config.LOCAL_HOST, running))
            time.sleep(1.5)
            return
        # 是别的程序占着，往后顺延端口
        try:
            httpd, port = bind_server(Handler, config.SERVER_HOST, config.SERVER_PORT)
        except Exception as e:                      # noqa: BLE001
            print("  [错误] %s" % e)
            print("  请关闭占用端口的程序后重试。")
            return
        print("  端口 %d 被占用，已自动切换到 %d" % (config.SERVER_PORT, port))

    url = "http://%s:%d/" % (config.LOCAL_HOST, port)
    print("  轮询周期：行情 %d 秒 / 深度分析 %d 秒" % (config.POLL_INTERVAL, config.POLL_DEEP))
    print_access(port)
    print("  按 Ctrl+C 停止")
    print("  " + "-" * 66)

    STORE.start()

    if config.AUTO_OPEN_BROWSER:
        def _open():
            time.sleep(1.0)
            open_url(url)
        threading.Thread(target=_open, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        STORE.running = False
        httpd.server_close()
        # 恢复控制台代码页，避免批处理后续的 pause 提示乱码
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(936)
        except Exception:
            pass


if __name__ == "__main__":
    main()
