#!/data/data/com.termux/files/usr/bin/bash
# ==========================================================
# 交易很轻松 · 安卓 Termux 一次性安装
# 用法：bash ~/jyhqs/termux/install.sh
#       JYHQS_MIRROR=tuna bash ~/jyhqs/termux/install.sh   ← 自动换清华源
# ==========================================================
set -u

SRC="$PREFIX/etc/apt/sources.list"
TUNA="https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main"

echo ""
echo "  交易很轻松 · 手机环境安装"
echo "  ------------------------------------------"

# ---------- 0. 镜像源 ----------
if grep -q "packages.termux.dev" "$SRC" 2>/dev/null; then
    if [ "${JYHQS_MIRROR:-}" = "tuna" ]; then
        echo "  [0/4] 切换到清华镜像…"
        sed -i "s@^\(deb.*stable main\)\$@#\1\ndeb $TUNA stable main@" "$SRC"
        apt update >/dev/null 2>&1
        echo "  [OK] 已换成清华源"
    else
        echo "  [注意] 现在用的是官方源，国内下载可能只有几 KB/s。"
        echo "         嫌慢先换源：termux-change-repo（选 TUNA 清华）"
        echo "         或者重跑：JYHQS_MIRROR=tuna bash $0"
        echo ""
    fi
fi

# ---------- 1. Python ----------
if command -v python >/dev/null 2>&1; then
    echo "  [跳过] 已有 Python：$(python -V 2>&1)"
else
    echo "  [1/4] 安装 Python（几十 MB，慢的话几分钟，别急着关）…"
    apt update >/dev/null 2>&1
    pkg install -y python || {
        echo "  [失败] Python 装不上。多半是网太慢或源不通，先换源再试："
        echo "         termux-change-repo"
        exit 1
    }
fi

PYVER=$(python -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>/dev/null)
case "$PYVER" in
    3.9|3.10|3.11|3.12|3.13|3.14) echo "  [OK] Python $PYVER 可用" ;;
    *) echo "  [警告] Python $PYVER 可能不受支持，建议 >= 3.9" ;;
esac

# ---------- 2. termux-api（可选，用来自动拉起浏览器） ----------
echo "  [2/4] 安装 termux-api（可选，失败不影响使用）…"
pkg install -y termux-api >/dev/null 2>&1 \
    && echo "  [OK] termux-api 已装" \
    || echo "  [跳过] termux-api 未装上，启动后手动开浏览器即可"

# ---------- 3. 自检：能不能 import 项目模块 ----------
echo "  [3/4] 自检项目文件…"
APP="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP" || exit 1
if python -c "import sys;sys.path.insert(0,'.');import server;print('ok')" >/dev/null 2>&1; then
    echo "  [OK] 项目自检通过：$APP"
else
    echo "  [失败] 项目自检不通过，先手动跑一次看报错："
    echo "         cd $APP && python server.py"
    exit 1
fi

# ---------- 4. 写快捷命令 ----------
echo "  [4/4] 写入快捷命令…"
if ! grep -q "alias jyhqs=" "$HOME/.bashrc" 2>/dev/null; then
    printf '\n# 交易很轻松\nalias jyhqs="bash %s/termux/start.sh"\n' "$APP" >> "$HOME/.bashrc"
    echo "  [OK] 已添加：jyhqs"
else
    echo "  [跳过] jyhqs 已存在"
fi

echo "  ------------------------------------------"
echo "  安装完成。"
echo ""
echo "  下次启动：重开 Termux，输入 jyhqs 回车"
echo "  现在就启动：bash $APP/termux/start.sh"
echo ""
echo "  第一次打开页面需要 2~5 秒抓数据，耐心等一下。"
echo ""
