# -*- coding: utf-8 -*-
"""文件简介：确保 clash 已启动（run_daily.bat 用）。就绪 exit 0，起不来 exit 1。

为什么不让 bat 自己 start：2026-11-07 那次 `start "" /min clash…` 之后端口一度通、进程随后消失，
而且 cmd 起控制台程序容易跟父进程的句柄绑在一起。proxyctl.start() 用 DETACHED_PROCESS 起、
带 20 秒轮询等端口，是这套项目里已经跑了半个月的路径，bat 直接复用。
"""
import sys

from .. import proxyctl


def run(argv=None):
    ok = proxyctl.start(log=lambda m: print("[ensure_proxy] " + m))
    print("代理就绪（7890 可连）" if ok else "代理没起来（7890 连不上）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
