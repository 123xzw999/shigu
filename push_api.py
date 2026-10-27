# -*- coding: utf-8 -*-
"""
push_api.py —— 用 GitHub Git Data API 推送（本机 git push 走不通时的兜底）

背景：这台机器只有代理能出网，而代理对 github.com:443 是坏的（502），
但 api.github.com 正常。所以 git push 走不通，改用 REST API 直接建 blob/tree/commit/ref。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.request

REPO_DIR = r"C:\Users\PC\Desktop\交易很轻松"
OWNER, REPO = "123xzw999", "shigu"
MSG = sys.argv[1] if len(sys.argv) > 1 else "update"

TOKEN = subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def api(method, path, data=None):
    url = "https://api.github.com/repos/%s/%s%s" % (OWNER, REPO, path)
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "token " + TOKEN,
        "Accept": "application/vnd.github+json",
        "User-Agent": "shigu-deploy",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        txt = r.read().decode("utf-8")
        return json.loads(txt) if txt.strip() else {}


def main():
    files = subprocess.check_output(["git", "ls-files"], cwd=REPO_DIR, text=True).splitlines()
    files = [f for f in files if f and not f.startswith(".git/")]
    print("文件数: %d" % len(files))

    # 已有 main 分支就带 parent，否则是首次提交
    parent = None
    try:
        r = api("GET", "/git/ref/heads/main")
        parent = r["object"]["sha"]
        print("已有 main: %s" % parent[:8])
    except Exception:
        print("首次提交（main 不存在）")

    items = []
    for i, f in enumerate(files, 1):
        full = os.path.join(REPO_DIR, f)
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as fh:
            raw = fh.read()
        # 纯文本走 utf-8 编码更省流量，二进制走 base64
        try:
            txt = raw.decode("utf-8")
            if "\x00" not in txt:
                blob = api("POST", "/git/blobs", {"content": txt, "encoding": "utf-8"})
            else:
                raise UnicodeDecodeError("b", b"", 0, 1, "bin")
        except (UnicodeDecodeError, ValueError):
            blob = api("POST", "/git/blobs",
                       {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"})
        items.append({"path": f, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print("  [%d/%d] %s (%d B)" % (i, len(files), f, len(raw)))

    tree = api("POST", "/git/trees", {"tree": items})
    print("tree: %s" % tree["sha"][:8])

    payload = {"message": MSG, "tree": tree["sha"]}
    if parent:
        payload["parents"] = [parent]
    commit = api("POST", "/git/commits", payload)
    print("commit: %s" % commit["sha"][:8])

    if parent:
        api("PATCH", "/git/refs/heads/main", {"sha": commit["sha"], "force": True})
    else:
        api("POST", "/git/refs", {"ref": "refs/heads/main", "sha": commit["sha"]})
    print("已推送到 https://github.com/%s/%s" % (OWNER, REPO))


if __name__ == "__main__":
    main()
