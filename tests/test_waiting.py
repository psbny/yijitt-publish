# -*- coding: utf-8 -*-
"""文件简介：waiting 过期判定（m07968 回归）。用 first_at 判过期，避免每轮回补把 at 刷新后永不过期。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tarot_pipeline.pipeline import _waiting_expired  # noqa: E402

NOW = dt.datetime(2026, 11, 12, 18, 0, 0).timestamp()
DAYS, HOLD, LIVE, WINDOW = 20.0, 3.0, 3.0, 20.0
results = []


def case(name):
    def deco(fn):
        try:
            fn()
            results.append((name, None))
        except AssertionError as exc:
            results.append((name, str(exc)))
        return fn
    return deco


def iso(days_ago):
    return (dt.datetime.fromtimestamp(NOW) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")


@case("hold 2 天：继续等")
def _():
    r = {"status": "hold", "at": iso(0), "first_at": iso(2)}
    assert _waiting_expired(r, NOW, DAYS, HOLD, LIVE) is None


@case("hold 4 天：放弃")
def _():
    r = {"status": "hold", "at": iso(0), "first_at": iso(4)}
    why = _waiting_expired(r, NOW, DAYS, HOLD, LIVE)
    assert why and "仍不齐" in why, why


@case("每轮刷新 at 不再延长寿命（关键回归）")
def _():
    # at 是"刚刚"，first_at 是 5 天前 → 必须按 first_at 判过期
    r = {"status": "hold", "at": iso(0), "first_at": iso(5)}
    assert _waiting_expired(r, NOW, DAYS, HOLD, LIVE) is not None


@case("no_subs 19 天：还在窗口内")
def _():
    r = {"status": "no_subs", "at": iso(0), "first_at": iso(19)}
    assert _waiting_expired(r, NOW, DAYS, HOLD, LIVE) is None


@case("no_subs 21 天：放弃")
def _():
    r = {"status": "no_subs", "at": iso(0), "first_at": iso(21)}
    why = _waiting_expired(r, NOW, DAYS, HOLD, LIVE)
    assert why and "超过" in why, why


@case("live_gone 4 天：放弃")
def _():
    r = {"status": "live_gone", "at": iso(0), "first_at": iso(4)}
    assert _waiting_expired(r, NOW, DAYS, HOLD, LIVE) is not None


@case("老记录没有 first_at：退回用 at")
def _():
    r = {"status": "hold", "at": iso(9)}
    assert _waiting_expired(r, NOW, DAYS, HOLD, LIVE) is not None


@case("时间解析不了：不丢（宁可多试一轮）")
def _():
    r = {"status": "hold", "at": "unknown"}
    assert _waiting_expired(r, NOW, DAYS, HOLD, LIVE) is None


def main():
    failed = 0
    for name, err in results:
        if err:
            failed += 1
            print("FAIL %s：%s" % (name, err))
        else:
            print("PASS %s" % name)
    print("waiting 过期判定：%d 项，%d failed" % (len(results), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
