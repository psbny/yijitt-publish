# -*- coding: utf-8 -*-
r"""文件简介：标题处理——默认**不翻**，只做清洗后把原标题交给平台。

背景（m04769）：2026-11-06 实测 35/35 条外语标题被平台自己翻成中文，我们自己翻是多一个会坏的环节。
现在只剩一条可选路径：`translate.use_google: true` 时用谷歌免费接口直译（带退避重试），失败退回原文。
模型翻译（原 外部模型通道 通道）已随 m07729 下线，需要时用 `llm.py` 的本地网关。
"""
from __future__ import annotations

import re
import time

import requests

# 直译后常见生硬说法 -> 塔罗圈惯用词
TERMS = [
    ("没有联系", "断联"), ("无联系", "断联"), ("不要接触", "断联"),
    ("所有迹象", "全星座"), ("所有星座", "全星座"), ("所有标志", "全星座"),
    ("选择一张卡", "选组"), ("挑一张卡", "选组"), ("选择卡片", "选组"),
    ("你的感受", "你的心意"), ("他们的感受", "他们的心意"),
    ("接下来的事", "接下来会发生什么"), ("下一步", "接下来"),
    ("秘密", "藏起来的事"), ("隐藏的事", "藏起来的事"),
]

_JUNK = [
    r"\bALL\s*SIGNS?\b", r"\bAll\s+Signs?\b", r"\bPICK\s*A\s*CARD\b",
    r"\bPick\s+a\s+Card\b", r"\bTimeless\b", r"\bGeneral\b", r"\bTarot\b",
    r"\bCollective\b", r"\bExtended\b", r"\bFull\s+Reading\b",
]
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")


def _clean_raw(t: str) -> str:
    s = t or ""
    for pat in _JUNK:
        s = re.sub(pat, " ", s, flags=re.I)
    s = re.sub(r"[|｜]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -–—:：,，.。")
    return s


def _polish(t: str) -> str:
    s = (t or "").strip()
    for a, b in TERMS:
        s = s.replace(a, b)
    s = re.sub(r"\s{2,}", " ", s).strip(' "\'' + "“”‘’")
    return s


def _proxy_for(cfg: dict) -> dict:
    p = cfg.get("proxy") or ""
    if not p:
        try:
            from . import youtube as _yt
            p = _yt.detect_proxy() or ""
        except Exception:
            p = ""
    return {"http": p, "https": p} if p else {}


def _google(cfg: dict, text: str) -> str:
    """谷歌免费接口。m04769：4 路并发就会被限流（回 HTML 而不是 JSON），所以带退避重试。"""
    tc = cfg.get("translate") or {}
    tries = max(1, int(tc.get("google_retries") or 3))
    backoff = float(tc.get("google_backoff") or 2.0)
    url = "https://translate.googleapis.com/translate_a/single"
    params = {"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text}
    err = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=25,
                             proxies=_proxy_for(cfg) or None)
            if r.status_code != 200:
                raise RuntimeError("HTTP %d" % r.status_code)
            j = r.json()
            out = "".join(x[0] for x in (j[0] or []) if x and x[0])
            if out.strip():
                return out
            raise RuntimeError("返回空译文")
        except Exception as e:
            err = e
            if i < tries - 1:
                time.sleep(backoff * (i + 1))
    raise RuntimeError("%s（已重试 %d 次）" % (str(err)[:80], tries))


def translate_title(cfg: dict, yt_title: str, cn_name: str, vtype: str, log=print) -> str:
    """返回中文标题（不含【博主】前缀）。"""
    tc = cfg.get("translate") or {}
    max_chars = int(tc.get("max_chars") or 34)
    src = _clean_raw(yt_title) or yt_title

    # m04769：默认**不翻**，直接交清洗后的原标题——平台会翻成中文
    #（2026-11-06 实测 35/35 条外语标题全被平台翻成中文，自己翻反而多一个会坏的环节）。
    # m07729：原 外部模型通道 通道已下线；需要自己翻时把 use_google 打开即可（失败退回原文）。
    if not tc.get("use_google"):
        return src[:max_chars]
    if tc.get("use_google") and src:
        try:
            txt = _polish(_google(cfg, src))
            if txt:
                return txt[:max_chars]
        except Exception as e:
            log("    [Google 翻译失败] %s" % str(e)[:90])

    log("    [翻译降级] 保留清洗后的原文")
    return src[:max_chars]

