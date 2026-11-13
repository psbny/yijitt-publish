# -*- coding: utf-8 -*-
"""文件简介：探测本机端口是否在监听（run_daily.bat 用）。开着 exit 0，没开 exit 1。

为什么不用 netstat | findstr：2026-11-07 那条管道卡死过一次，findstr 变僵尸等 stdin，
整晚没跑起来。socket 连接法是秒回、不会卡。
"""
import socket
import sys


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = int(argv[0]) if argv else 7890
    s = socket.socket()
    s.settimeout(1.5)
    try:
        ok = s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        ok = False
    finally:
        s.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
