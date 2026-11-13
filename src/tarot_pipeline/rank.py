# -*- coding: utf-8 -*-
"""文件简介：按标题吸引力排序（用户 m02671 ①——多视频博主按标题精彩程度取前三个）。

RSS 给的标题已经够判断，不必先拿详情。一个博主一次请求，成本很低。
通道是 `llm.py` 的本地网关链（m07729：旧模型通道停用）。
失败就退回原顺序（RSS 是新到旧），不影响主流程。
"""
import json
import os

from . import llm
from . import paths


SYSTEM = (
    "你是塔罗/星座频道的运营，熟悉中国观众爱看什么。"
    "我会给你同一个博主最近发的若干条英文视频标题，你要按"
    "「最可能让中国观众点开看」的程度排序。"
    "只输出序号，用英文逗号分隔，例如 3,1,5,2。不要解释，不要加任何文字。"
)


def _ask(cfg, cn, titles, log=print):
    lines = ["博主：%s，共 %d 条：" % (cn, len(titles))]
    for i, t in enumerate(titles, 1):
        lines.append("%d) %s" % (i, t))
    lines.append("请只回复序号，逗号分隔。")
    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]
    # max_tokens 与 translate 的老结论对齐（m02865）：推理模型先写思考链，给小了正文会空
    raw, _gw = llm.chat(cfg, msgs, max_tokens=4000, timeout=90, log=log, tag="标题排序")
    return raw


def _parse(text, n):
    """从模型回复里抽出序号列表（1 起）。"""
    out, seen = [], set()
    buf = ""
    for ch in text:
        if ch.isdigit():
            buf += ch
        else:
            if buf:
                v = int(buf)
                if 1 <= v <= n and v not in seen:
                    out.append(v - 1)
                    seen.add(v)
                buf = ""
    if buf:
        v = int(buf)
        if 1 <= v <= n and v not in seen:
            out.append(v - 1)
    return out


RANK_CACHE = os.path.join(paths.DATA_DIR, "rank-cache.json")


def _cache_key(cn: str, items: list) -> str:
    return cn + "|" + ",".join(sorted(str(v) for v, _t in items))


def _load_cache() -> dict:
    try:
        with open(RANK_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(RANK_CACHE), exist_ok=True)
        tmp = RANK_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, RANK_CACHE)
    except Exception:
        pass


def rank(cn, items, cfg, top=3, log=print):
    """items = [(video_id, title), ...]，返回按吸引力排好序的同样结构。"""
    # m04253：同一博主同一批视频只问一次模型（缓存 key = 频道 + 视频 id 集合）
    ckey = _cache_key(cn, items)
    _c = _load_cache()
    if isinstance(_c.get(ckey), list) and len(_c[ckey]) == len(items):
        log("    标题排序：命中缓存")
        return _c[ckey]

    if len(items) <= 1:
        return list(items)
    # 只把前 12 条送给模型：实测 15 条要 34 秒、6 条只要 7 秒，
    # 而调用方最多只要前 3 条，没必要让模型排完全部（2026-11-06 实测）
    _CAP = 12
    head_items = list(items[:_CAP])
    titles = [(t or "").strip() or "(无标题)" for _v, t in head_items]
    try:
        raw = _ask(cfg, cn, titles, log=log)
    except Exception as e:
        log("    [排序降级] %s" % str(e)[:110])
        return list(items)
    order = _parse(raw, len(head_items))
    if not order:
        log("    [排序降级] 模型没给出可用序号：%r" % raw[:60])
        return list(items)
    # 模型给全了就用它，没给全的按原顺序补在后面
    head = [head_items[i] for i in order]
    tail = [it for i, it in enumerate(head_items) if i not in set(order)]
    tail += list(items[_CAP:])
    log("    标题排序：%s" % raw[:40])
    _c2 = _load_cache()
    _c2[ckey] = head + tail
    _save_cache(_c2)
    return head + tail


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    # 项目根目录：本文件在 <root>\lib\rank.py，往上两级即可，别写死盘符
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import pipeline
    cfg = pipeline.load_config()
    demo = [("a", "URGENT 🔴 They Admit Everything Tonight"),
            ("b", "Pick a Crystal: What Is Coming Towards You"),
            ("c", "Weekly Tarot: Your Energy This Week"),
            ("d", "ALL SIGNS: The Truth They Never Told You")]
    for vid, title in rank("测试", demo, cfg):
        print(vid, title)