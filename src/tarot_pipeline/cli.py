# -*- coding: utf-8 -*-
"""文件简介：命令行入口 `tarot-pipeline`，把原来一堆散装脚本收成一个命令。

子命令：
  run             主流程（默认，等同以前 python pipeline.py）
  report          日报（等同以前 python report.py，可 --print / --push / --file）
  adopt-orphans   把最近 N 小时生成的裸草稿补封面/价格/排期
  portcheck       探测端口是否在监听（run_daily.bat 用）
  ensure-proxy    确保 clash 已启动（run_daily.bat 用）

例：
  tarot-pipeline run --all                    # 扫描+提交+等 AI+发布（会扣能量币）
  tarot-pipeline run --dry-run --limit 3      # 只看不提交
  tarot-pipeline report --push                # 生成日报并推到IM
  tarot-pipeline adopt-orphans --hours 6 --date 2026-11-09
"""
from __future__ import annotations

import sys

USAGE = """tarot-pipeline <子命令> [参数]

子命令：
  run             主流程：扫 YouTube 更新 -> 下字幕 -> 判类型 -> 提交 -> 排期
                  参数见 `tarot-pipeline run --help`（--all / --commit / --dry-run 等）
  report          生成日报；--print 只打印，--push 推送到IM 机器人等通道
  adopt-orphans   把最近 H 小时生成的裸草稿补上封面/价格/排期
                  --hours 6 --date 2026-11-09 --dry-run
  portcheck       探测本机端口：tarot-pipeline portcheck 7890（开着 exit 0）
  ensure-proxy    确保 clash 在跑：tarot-pipeline ensure-proxy

不带子命令时默认跑 `run`。
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["run"]
    cmd, rest = argv[0], argv[1:]

    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd in ("-V", "--version", "version"):
        from . import __version__
        print("tarot-pipeline %s" % __version__)
        return 0

    if cmd == "run":
        from . import pipeline
        return pipeline.main(rest)

    if cmd == "report":
        from . import report
        return report.main(rest)

    if cmd == "adopt-orphans":
        from . import pipeline
        return pipeline.main(_adopt_argv(rest))

    if cmd == "portcheck":
        from .tools.portcheck import run as portcheck_run
        return portcheck_run(rest)

    if cmd == "ensure-proxy":
        from .tools.ensure_proxy import run as ensure_proxy_run
        return ensure_proxy_run(rest)

    print("未知子命令：%s\n" % cmd, file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


def _adopt_argv(rest):
    """把 `adopt-orphans --hours 6` 翻译成主流程认识的 `--adopt-orphans 6`。"""
    hours = "6"
    tail = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--hours", "-H"):
            hours = rest[i + 1]
            i += 2
            continue
        if a == "--hours=" or a.startswith("--hours="):
            hours = a.split("=", 1)[1]
            i += 1
            continue
        tail.append(a)
        i += 1
    return ["--adopt-orphans", hours] + tail


if __name__ == "__main__":
    raise SystemExit(main())
