# -*- coding: utf-8 -*-
"""文件简介：章节名"星座正名"的离线单测（m06052；m07729 换成 llm 网关链）。

不起网络：把 `chapterai.llm.chat` 换成假函数，只验证
①认出 12 个就返回映射；②模型乱答 / 只认出一部分 / 超时 -> 返回 None（调用方保持 hold）；
③本来就齐 / 开关关掉 / 网关全挂 -> 不采纳模型结果。

运行：python -m pytest tests -q   或   python tests/test_chapterai.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tarot_pipeline import chapterai
from tarot_pipeline import core

# 复刻 2026-11-08 Queen hPW8wr-32w0 的真实写法：后三条是缩写
REAL_QUEEN = "\n".join([
    "ARIES 00:00:00", "TAURUS 00:13:30", "GEMINI 00:26:00", "CANCER 00:39:00",
    "LEO 00:52:00", "VIRGO 01:05:00", "LIBRA 01:18:00", "SCORPIO 01:31:00",
    "SAG 02:01:00", "CAP 02:14:00", "AQUA 02:27:30", "PISCES 02:40:00",
])

GOOD_JSON = ('{"1":"白羊座","2":"金牛座","3":"双子座","4":"巨蟹座","5":"狮子座","6":"处女座",'
             '"7":"天秤座","8":"天蝎座","9":"射手座","10":"摩羯座","11":"水瓶座","12":"双鱼座"}')


def _cfg(**over):
    cc = {"enabled": True, "timeout": 5}
    cc.update(over)
    return {
        "chapterai": cc,
        "llm": {"providers": [{"name": "假网关", "model": "fake-model"}]},
    }


def _fake_chat(reply):
    """把 chapterai.llm.chat 换成固定回复；记录调用次数。"""
    calls = []

    def chat(cfg, messages, max_tokens=None, timeout=None, log=print, tag=""):
        calls.append({"messages": messages, "max_tokens": max_tokens,
                      "timeout": timeout, "tag": tag})
        if isinstance(reply, Exception):
            raise reply
        return reply, "假网关"

    chapterai.llm.chat = chat
    return calls


def _restore_chat():
    import importlib

    from tarot_pipeline import llm as _llm

    importlib.reload(_llm)          # 假 chat 是挂在 llm 模块上的，要重载回真函数
    importlib.reload(chapterai)


def test_real_queen_becomes_12_of_12():
    _fake_chat(GOOD_JSON)
    chs = core.parse_chapters(REAL_QUEEN)
    assert len(chs) == 12
    assert core.all_signs_incomplete(chs) is True, "起点应该是认不全（SAG/CAP/AQUA 三条缩写）"

    mapping = chapterai.normalize_signs(_cfg(), chs, log=lambda *a: None)
    assert mapping is not None and len(mapping) == 12
    assert set(mapping.values()) == set(core.ZODIAC_CN)

    # 只改名字，秒数必须原样
    before = [c.seconds for c in chs]
    for i, c in enumerate(chs):
        if i in mapping:
            c.name = mapping[i]
    assert [c.seconds for c in chs] == before
    assert core.all_signs_incomplete(chs) is False
    assert chs[8].name == "射手座" and chs[10].name == "水瓶座"
    _restore_chat()


def test_garbage_reply_returns_none():
    _fake_chat("抱歉，我不确定这些是不是星座。")
    chs = core.parse_chapters(REAL_QUEEN)
    assert chapterai.normalize_signs(_cfg(), chs, log=lambda *a: None) is None
    _restore_chat()


def test_partial_reply_returns_none():
    _fake_chat('{"1":"白羊座","2":"金牛座","9":"射手座"}')   # 只认出 3 个
    chs = core.parse_chapters(REAL_QUEEN)
    assert chapterai.normalize_signs(_cfg(), chs, log=lambda *a: None) is None
    _restore_chat()


def test_timeout_or_all_gateways_down_returns_none():
    """网关链全挂时抛 LLMError，normalize_signs 必须吞掉并返回 None。"""
    _fake_chat(RuntimeError("全部网关都失败：gateway-a：HTTP 500"))
    chs = core.parse_chapters(REAL_QUEEN)
    assert chapterai.normalize_signs(_cfg(), chs, log=lambda *a: None) is None
    _restore_chat()


def test_complete_chapters_skip_model():
    def boom(*a, **kw):
        raise AssertionError("本来就齐了，不该调模型")

    chapterai.llm.chat = boom
    good = "\n".join(
        "%s — %02d:%02d:00" % (n, (i * 13) // 60, (i * 13) % 60)
        for i, n in enumerate(core.ZODIAC_CN)
    )
    chs = core.parse_chapters(good)
    assert core.all_signs_incomplete(chs) is False
    assert chapterai.normalize_signs(_cfg(), chs, log=lambda *a: None) is None
    _restore_chat()


def test_disabled_switch_skips_model():
    def boom(*a, **kw):
        raise AssertionError("开关关掉时不该调模型")

    chapterai.llm.chat = boom
    chs = core.parse_chapters(REAL_QUEEN)
    assert chapterai.normalize_signs(_cfg(enabled=False), chs, log=lambda *a: None) is None
    _restore_chat()


def test_screen_passes_chapter_names_to_llm():
    """screen()：选组视频把章节名发出去，模型回序号 -> 只保留对应几条。"""
    calls = _fake_chat("1,3")
    chs = core.parse_chapters("Home 00:00:00\nPile 1 00:01:00\nPile 2 00:11:00\nPile 3 00:21:00\n")
    kept = chapterai.screen(_cfg(), "某博主", "标题", core.TYPE_PICK, chs, log=lambda *a: None)
    assert kept is not None and [c.name for c in kept] == ["Home", "Pile 2"]
    assert calls and "Pile 1" in calls[0]["messages"][1]["content"]
    _restore_chat()


def test_min_signs_partial_mapping_for_prejudge():
    """m06495：判定前兜底只要求认出 10 个（够判全星座就行），默认仍要 12 个。"""
    import json as _json
    ten = _json.dumps({str(i + 1): n for i, n in enumerate(core.ZODIAC_CN[:10])},
                      ensure_ascii=False)
    _fake_chat(ten)
    chs = core.parse_chapters(REAL_QUEEN)
    # 默认 12：只认出 10 个，不采纳
    assert chapterai.normalize_signs(_cfg(), chs, log=lambda *a: None) is None
    # min_signs=10：采纳，且只改名字
    before = [c.seconds for c in chs]
    got = chapterai.normalize_signs(_cfg(), chs, log=lambda *a: None, min_signs=10)
    assert got and len(set(got.values())) == 10, got
    assert [c.seconds for c in chs] == before
    _restore_chat()


def test_prejudge_signs_before_classify():
    """m06495：章节 12 条但名字是没见过的写法时，判定前先让模型正名，别再判成能量。"""
    from tarot_pipeline import pipeline as P
    italian = ("Introduzione 00:00\nAriete 01:00\nToro 12:00\nGemelli 24:00\n"
               "Cancro 35:00\nLeone 46:00\nVergine 57:00\nBilancia 1:08:00\n"
               "Scorpione 1:19:00\nSagittario 1:30:00\nCapricorno 1:41:00\n"
               "Acquario 1:52:00\nPesci 2:03:00")
    chs = core.parse_chapters(italian)
    assert len(core.zodiac_hits_names(chs)) == 12      # A 层：字典已能认
    # 换成模型认不出的写法，验证 C 层兜得住
    for i, c in enumerate(chs):
        c.name = "第%d组" % (i + 1)
    assert len(core.zodiac_hits_names(chs)) == 0
    _fake_chat(GOOD_JSON)
    mapping = P.prejudge_signs(_cfg(), chs, 7200, log=lambda *a: None)
    assert mapping and len(set(mapping.values())) == 12, mapping
    assert core.classify(chs, 7200, "") == core.TYPE_ALL_SIGNS
    _restore_chat()


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, "->", type(e).__name__, e)
    print("\n%d failed" % fails)
    sys.exit(1 if fails else 0)
