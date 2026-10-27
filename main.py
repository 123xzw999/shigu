# -*- coding: utf-8 -*-
"""
识股 · Android 入口
===================
这个文件只给 APK 用。电脑上仍然双击「启动.bat」跑 server.py。

APK 里的工作方式：
  1. 后台线程起一个本地 HTTP 服务（127.0.0.1:8765，只监听本机）
  2. 前台用 Android 原生 WebView 加载它
  3. 界面代码和电脑版完全同一份（web/ 目录），不用维护两套

为什么必须是「本地服务 + WebView」而不是直接放个网页：
  新浪的行情接口会校验 Referer，浏览器发不了自定义 Referer，
  所以抓取必须在 Python 侧做 —— 这也是为什么静态托管跑不起来。
"""

import os
import sys
import threading
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

PORT = 8765
_BOOT_LOG = os.path.join(BASE, "boot_error.log")


def _log_err(where, e):
    try:
        with open(_BOOT_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n%s\n" % (where, e, traceback.format_exc()))
    except Exception:
        pass


# ---------------------------------------------------------------- SSL 证书
# Android 上 Python 自带的 ssl 没有系统 CA bundle，访问 https 会直接报
# CERTIFICATE_VERIFY_FAILED。certifi 在 requirements 里，这里指给它。
def _setup_ssl():
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except Exception as e:                                  # noqa: BLE001
        _log_err("ssl", e)


# ---------------------------------------------------------------- 本地服务
def _boot_server():
    try:
        _setup_ssl()
        from core import config
        config.AUTO_OPEN_BROWSER = False
        config.SERVER_HOST = "127.0.0.1"
        config.SERVER_PORT = PORT

        import server as srv
        from http.server import ThreadingHTTPServer

        start_code = srv.STORE.watch[0] if srv.STORE.watch else "sh600519"
        srv.STORE.set_current(start_code, 240)
        srv.STORE.start()

        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), srv.Handler)
        httpd.daemon_threads = True
        httpd.serve_forever()
    except Exception as e:                                  # noqa: BLE001
        _log_err("server", e)


threading.Thread(target=_boot_server, daemon=True).start()


# ---------------------------------------------------------------- 前台
from kivy.app import App                                    # noqa: E402
from kivy.clock import Clock                                # noqa: E402
from kivy.core.window import Window                         # noqa: E402
from kivy.uix.label import Label                            # noqa: E402

SPLASH = "ShiGu\nstarting market service..."


class ShiguApp(App):
    def build(self):
        Window.clearcolor = (0.04, 0.05, 0.07, 1)
        # 给服务一点时间把第一轮数据拉回来，再挂 WebView，避免一进去就是空白页
        Clock.schedule_once(self._attach_webview, 1.6)
        return Label(text=SPLASH, font_size="15sp", color=(0.7, 0.75, 0.82, 1))

    def _attach_webview(self, dt):
        try:
            from jnius import autoclass
            from android.runnable import run_on_ui_thread
            from android import mActivity
        except Exception as e:                              # noqa: BLE001
            _log_err("jnius", e)
            return

        @run_on_ui_thread
        def _go():
            try:
                WebView = autoclass("android.webkit.WebView")
                WebViewClient = autoclass("android.webkit.WebViewClient")
                LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")
                Build = autoclass("android.os.Build$VERSION")

                wv = WebView(mActivity)
                st = wv.getSettings()
                st.setJavaScriptEnabled(True)
                st.setDomStorageEnabled(True)
                st.setDatabaseEnabled(True)
                st.setUseWideViewPort(True)
                st.setLoadWithOverviewMode(True)
                st.setAllowFileAccess(True)
                try:
                    st.setMixedContentMode(0)               # ALWAYS_ALLOW
                except Exception:
                    pass
                if Build.SDK_INT >= 19:
                    WebView.setWebContentsDebuggingEnabled(False)

                wv.setWebViewClient(WebViewClient())
                wv.loadUrl("http://127.0.0.1:%d/" % PORT)
                mActivity.addContentView(wv, LayoutParams(-1, -1))
            except Exception as e:                          # noqa: BLE001
                _log_err("webview", e)

        _go()


if __name__ == "__main__":
    ShiguApp().run()
