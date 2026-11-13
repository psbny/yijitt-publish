# -*- coding: utf-8 -*-
"""文件简介：回补池去重（2026-11-12 修）。同一条视频既在当天扫描又在 waiting 时只处理一次。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tarot_pipeline.pipeline import _dedupe_candidates  # noqa: E402

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


class Stub(object):
    def __init__(self, vid):
        self.video_id = vid
        self.title = "t"


def item(vid, retry=False):
    d = {"blogger": {"cn": "测试", "handle": "@x", "name": "x"}, "stub": Stub(vid)}
    if retry:
        d["_retry"] = True
    return d


@case("两边都有的只留当天扫描那份")
def _():
    fresh = [item("A"), item("B")]
    retry = [item("A", retry=True), item("C", retry=True)]
    kept, dup = _dedupe_candidates(fresh, retry)
    assert dup == 1, dup
    ids = [c["stub"].video_id for c in kept + fresh]
    assert ids.count("A") == 1, ids
    assert sorted(ids) == ["A", "B", "C"], ids


@case("没有重叠：回补一条不少")
def _():
    fresh = [item("A")]
    retry = [item("B", retry=True), item("C", retry=True)]
    kept, dup = _dedupe_candidates(fresh, retry)
    assert dup == 0, dup
    assert [c["stub"].video_id for c in kept] == ["B", "C"]
    assert [c["stub"].video_id for c in kept + fresh] == ["B", "C", "A"]


@case("没有回补池：原样返回")
def _():
    kept, dup = _dedupe_candidates([item("A")], [])
    assert kept == [] and dup == 0


@case("回补条目缺 stub：保留，不误删")
def _():
    kept, dup = _dedupe_candidates([item("A")], [{"blogger": {"cn": "x"}}])
    assert dup == 0 and len(kept) == 1


def main():
    failed = 0
    for name, err in results:
        if err:
            failed += 1
            print("FAIL %s：%s" % (name, err))
        else:
            print("PASS %s" % name)
    print("回补去重：%d 项，%d failed" % (len(results), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
