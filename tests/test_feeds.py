# -*- coding: utf-8 -*-
"""lib/feeds.py 的相对时间解析（2026-11-09 直播回放那次 bug 的回归测试）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tarot_pipeline.feeds import parse_age  # noqa: E402

CASES = [
    # (输入, 期望秒)
    ("6d ago", 518400),
    ("2 days ago", 172800),
    ("3 hours ago", 10800),
    ("45 minutes ago", 2700),
    ("2w ago", 1209600),
    # 直播回放 / 首映：YouTube 会在前面加词，旧正则因为 ^...$ 全判空，
    # 结果整条被丢弃 —— Kitty / Harmonia 的全星座就是这么漏的。
    ("Streamed 2 days ago", 172800),
    ("Premiered 9 hours ago", 32400),
    ("Live 1 day ago", 86400),
    # 中文界面
    ("直播时间：3 天前", 259200),
    ("9小时前", 32400),
    ("2 周前", 1209600),
    ("1 个月前", 2592000),
    # 认不出的必须返回 None，别乱猜
    ("No views", None),
    ("2026", None),
    ("", None),
]


def main():
    failed = 0
    for text, want in CASES:
        got = parse_age(text)
        if got != want:
            failed += 1
            print("FAIL %r -> %r（期望 %r）" % (text, got, want))
    print("parse_age: %d 项，%d failed" % (len(CASES), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
