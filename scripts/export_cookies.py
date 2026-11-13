# 文件简介：从 waimian Chrome（CDP 9333）导出 YouTube 登录 cookie 到 data\yt-cookies.txt。
# 用法：先确认那个 Chrome 已开着并登录了 YouTube，然后 python scripts\\export_cookies.py
# 什么时候要重跑：日志出现 "Sign in to confirm you're not a bot" 或 cookie 过期（约 1-3 个月）。
import io
import json
import os
import sys
import time
import urllib.request

import websocket

CDP = "http://127.0.0.1:9333"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "yt-cookies.txt")


def export() -> int:
    lst = json.load(urllib.request.urlopen(CDP + "/json/list", timeout=8))
    pages = [t for t in lst if t.get("type") == "page"]
    if not pages:
        print("没找到可用的页面，先确认 Chrome 开着")
        return 0
    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=15,
                                     suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
    ws.recv()
    ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
    ck = (json.loads(ws.recv()).get("result") or {}).get("cookies") or []
    ws.close()

    lines = ["# Netscape HTTP Cookie File",
             "# 由 tools_export_cookies.py 从 waimian Chrome 导出（含登录态，勿外传）", ""]
    n, now = 0, time.time()
    for c in ck:
        dom = c.get("domain", "")
        if not (("google" in dom) or ("youtube" in dom)):
            continue
        exp = c.get("expires") or 0
        if exp and exp < now:
            continue
        name, val = c.get("name", ""), c.get("value", "")
        if not name:
            continue
        lines.append("\t".join([
            dom,
            "TRUE" if dom.startswith(".") else "FALSE",
            c.get("path") or "/",
            "TRUE" if c.get("secure") else "FALSE",
            str(int(exp) or 0), name, val,
        ]))
        n += 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("已写 %s：%d 条 cookie" % (OUT, n))
    return n


if __name__ == "__main__":
    sys.exit(0 if export() > 0 else 1)