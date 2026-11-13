# -*- coding: utf-8 -*-
r"""文件简介：解析博主清单 C:\path\to\jb.docx。

文档真实结构（119 段 / 110 非空）：一个条目可能跨多段，
  【中文名】名字 [备注] https://www.youtube.com/@handle/videos
  【俄罗斯3Hает】俄罗斯3Hает （链接进不去搜这个名字：...）
  https://www.youtube.com/@%D0%A2.../videos
  【魔法之谜】
  https://www.youtube.com/@Magicalmysterylifewitht/videos
所以按「遇到【】开新条目」累积，而不是一行一条。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from urllib.parse import unquote

_HEAD_RE = re.compile(r"【([^】]{1,40})】")
_URL_RE = re.compile(r"(https?://\S+|(?:www\.)?youtube\.com/\S+)", re.I)
_HANDLE_RE = re.compile(r"youtube\.com/(@[^/\s?]+)", re.I)
_CHANNEL_RE = re.compile(r"youtube\.com/channel/(UC[\w-]{10,})", re.I)
_SEARCH_HINT = re.compile(r"搜(?:这个名字|索)?[：:]\s*([^）)]+)")
_VIDEOS_SUFFIX = re.compile(r"/(videos|streams|shorts|featured)\b.*$", re.I)


@dataclass
class Blogger:
    cn: str            # 中文名（后台频道名就用这个）
    name: str          # 文档里的原名
    handle: str        # @xxx 或 UCxxx，抓取用；空表示没拿到
    url: str           # 规范化后的频道地址
    remark: str = ""   # 括号里的备注
    needs_search: str = ""  # 只有"搜这个名字"没有链接时，填搜索词
    ok: bool = True
    issue: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_url(u: str) -> str:
    u = u.strip().strip("（）()")
    if not u.lower().startswith("http"):
        u = "https://" + u.lstrip("/")
    u = _VIDEOS_SUFFIX.sub("", u)
    return u.rstrip("/")


def parse_paragraphs(paragraphs: list[str]) -> list[Blogger]:
    """把段落列表切成条目并解析。"""
    entries: list[list[str]] = []
    for raw in paragraphs:
        line = (raw or "").strip()
        if not line:
            continue
        if _HEAD_RE.match(line):
            entries.append([line])
        elif entries:
            entries[-1].append(line)
        else:  # 文档开头的裸行（没有【】），也收成一条
            entries.append([line])

    out: list[Blogger] = []
    for parts in entries:
        text = " ".join(parts)
        m = _HEAD_RE.search(text)
        if not m:
            continue
        cn = m.group(1).strip()
        rest = text[m.end():].strip()
        # 名字 = 文本开头、URL/备注之前的第一个词串
        url_m = _URL_RE.search(rest)
        name_part = rest[: url_m.start()].strip() if url_m else rest
        remark = ""
        rb = re.search(r"[（(]([^）)]*)[）)]", name_part)
        if rb:
            remark = rb.group(1).strip()
            name_part = name_part[: rb.start()].strip()
        name = name_part.strip() or cn
        url = _norm_url(url_m.group(1)) if url_m else ""
        hm = _HANDLE_RE.search(url) if url else None
        cm = _CHANNEL_RE.search(url) if url else None
        if hm:
            handle = unquote(hm.group(1))
        elif cm:
            handle = cm.group(1)   # /channel/UCxxx 形式，yt-dlp 同样接受
        else:
            handle = ""
        needs = ""
        sm = _SEARCH_HINT.search(remark or text)
        if sm and not handle:
            needs = sm.group(1).strip()

        b = Blogger(cn=cn, name=name, handle=handle, url=url, remark=remark, needs_search=needs)
        if not handle:
            b.ok = False
            b.issue = "无可用频道链接" + ("（需搜索）" if needs else "")
        elif "admin.example.com" in url:
            b.ok = False
            b.issue = "链接被误填成后台站内地址"
        out.append(b)
    return out


def load_from_docx(path: str) -> list[Blogger]:
    from docx import Document

    doc = Document(path)
    return parse_paragraphs([p.text for p in doc.paragraphs])


def dedupe_handle(bloggers: list[Blogger]) -> list[Blogger]:
    """同一 handle 只留第一条（文档里可能有重复频道）。"""
    seen = set()
    out = []
    for b in bloggers:
        key = b.handle.lower()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(b)
    return out
