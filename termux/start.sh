#!/data/data/com.termux/files/usr/bin/bash
# ==========================================================
# 交易很轻松 · 安卓 Termux 启动
# 用法：bash ~/jyhqs/termux/start.sh   或输入 jyhqs
# ==========================================================
set -u

APP="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP" || { echo "找不到项目目录：$APP"; exit 1; }

# 没有 python 就先装
if ! command -v python >/dev/null 2>&1; then
    echo "  还没装 Python，先跑一次：bash $APP/termux/install.sh"
    exit 1
fi

# 防止锁屏后 CPU 休眠把服务挂掉
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock 2>/dev/null && echo "  [OK] 已加唤醒锁（锁屏也不会断）"
fi

# 服务在跑就直接开浏览器，不重复启动
if python - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.build_opener(urllib.request.ProxyHandler({})) \
    .open("http://127.0.0.1:8765/api/status", timeout=2).read()
PY
then
    echo "  服务已在运行，直接打开浏览器。"
    command -v termux-open-url >/dev/null 2>&1 && termux-open-url "http://127.0.0.1:8765/"
    echo "  地址：http://127.0.0.1:8765/"
    exit 0
fi

echo "  启动中，浏览器会自动打开；没自动开就手动访问 http://127.0.0.1:8765/"
echo ""

exec python server.py
