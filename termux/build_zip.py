# -*- coding: utf-8 -*-
"""
打包「手机版」zip —— 给安卓 Termux 用
=====================================
用法：python termux/build_zip.py [输出路径]

只收手机真正需要的文件，全部 ASCII 文件名（Termux 里不会出现中文乱码），
顶层目录固定为 jyhqs，解压后就是 ~/jyhqs。
"""

import os
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = "jyhqs"

# (相对路径, 是否递归)
INCLUDE_FILES = ["server.py", "cli.py", "LICENSE", "README.md"]
INCLUDE_DIRS = ["core", "web", "termux"]
# 转折判断的模型参数和板块映射必须带上，否则手机版没有「转折点判断」
EXTRA = [("data", "watchlist.json"),
         ("data", "turning_profiles.json"),
         ("data", "sector_map.json")]

SKIP_DIR = {"__pycache__", ".git"}
SKIP_EXT = {".pyc", ".pyo", ".bat", ".png", ".jpg"}
SKIP_FILE = {"build_zip.py"}          # 打包脚本自身不进包


def collect():
    items = []
    for name in INCLUDE_FILES:
        p = os.path.join(BASE, name)
        if os.path.isfile(p):
            items.append((p, name))
    for d in INCLUDE_DIRS:
        root = os.path.join(BASE, d)
        for cur, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIR]
            for f in sorted(files):
                if os.path.splitext(f)[1].lower() in SKIP_EXT:
                    continue
                if f in SKIP_FILE:
                    continue
                p = os.path.join(cur, f)
                items.append((p, os.path.relpath(p, BASE).replace("\\", "/")))
    for sub, name in EXTRA:
        p = os.path.join(BASE, sub, name)
        if os.path.isfile(p):
            items.append((p, "%s/%s" % (sub, name)))
    return items


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "dist", "shigu-termux.zip")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    items = collect()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, rel in items:
            z.write(src, "%s/%s" % (TOP, rel))
    size = os.path.getsize(out)
    print("已生成：%s" % out)
    print("文件数：%d    大小：%.1f KB" % (len(items), size / 1024.0))
    for _, rel in items:
        print("  " + rel)


if __name__ == "__main__":
    main()
