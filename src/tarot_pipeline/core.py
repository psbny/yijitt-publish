# -*- coding: utf-8 -*-
"""文件简介：核心纯函数——时间戳解析、类型判定、标题拼接、计费、srt 清洗。

这一层不碰网络、不碰浏览器，全部可以离线单测。
所有规则都来自 2026-11-04 对 admin.example.com 的实际勘查。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from . import rules as _rules

# ---------------------------------------------------------------- 常量

ZODIAC_CN = [
    "白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
    "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座",
]
ZODIAC_ALIASES = {
    "白羊": "白羊座", "牡羊": "白羊座", "aries": "白羊座",
    "金牛": "金牛座", "taurus": "金牛座",
    "双子": "双子座", "gemini": "双子座",
    "巨蟹": "巨蟹座", "cancer": "巨蟹座",
    "狮子": "狮子座", "leo": "狮子座",
    "处女": "处女座", "室女": "处女座", "virgo": "处女座",
    "天秤": "天秤座", "天平": "天秤座", "libra": "天秤座",
    "天蝎": "天蝎座", "scorpio": "天蝎座",
    "射手": "射手座", "人马": "射手座", "sagittarius": "射手座",
    "摩羯": "摩羯座", "山羊": "摩羯座", "capricorn": "摩羯座",
    "水瓶": "水瓶座", "宝瓶": "水瓶座", "aquarius": "水瓶座",
    "双鱼": "双鱼座", "pisces": "双鱼座", "piscis": "双鱼座",
    # 西班牙语（拉美西语频道常见）
    "tauro": "金牛座", "geminis": "双子座", "g\u00e9minis": "双子座", "c\u00e1ncer": "巨蟹座",
    "escorpio": "天蝎座", "sagitario": "射手座", "capricornio": "摩羯座", "acuario": "水瓶座",
    # 葡萄牙语
    "touro": "金牛座", "g\u00eameos": "双子座", "c\u00e2ncer": "巨蟹座", "escorpi\u00e3o": "天蝎座",
    "sagit\u00e1rio": "射手座", "capric\u00f3rnio": "摩羯座", "aqu\u00e1rio": "水瓶座", "peixes": "双鱼座",
    "\u00e1ries": "白羊座", "le\u00e3o": "狮子座", "virgem": "处女座", "balan\u00e7a": "天秤座",
    # 意大利语（m06495：Bucci 那类频道整篇 ARIETE/TORO/GEMELLI，以前一个都认不出）
    "ariete": "白羊座", "toro": "金牛座", "gemelli": "双子座", "cancro": "巨蟹座",
    "leone": "狮子座", "vergine": "处女座", "bilancia": "天秤座", "scorpione": "天蝎座",
    "sagittario": "射手座", "capricorno": "摩羯座", "acquario": "水瓶座", "pesci": "双鱼座",
    # 俄语（卡娅 / 塔罗女王那类，章节名全是西里尔字母）
    "\u043e\u0432\u0435\u043d": "白羊座", "\u0442\u0435\u043b\u0435\u0446": "金牛座",
    "\u0431\u043b\u0438\u0437\u043d\u0435\u0446\u044b": "双子座", "\u0440\u0430\u043a": "巨蟹座",
    "\u043b\u0435\u0432": "狮子座", "\u0434\u0435\u0432\u0430": "处女座", "\u0432\u0435\u0441\u044b": "天秤座",
    "\u0441\u043a\u043e\u0440\u043f\u0438\u043e\u043d": "天蝎座", "\u0441\u0442\u0440\u0435\u043b\u0435\u0446": "射手座",
    "\u043a\u043e\u0437\u0435\u0440\u043e\u0433": "摩羯座", "\u0432\u043e\u0434\u043e\u043b\u0435\u0439": "水瓶座",
    "\u0440\u044b\u0431\u044b": "双鱼座",
    # 波兰语（伊娃博士那类：Waga / Skorpion / Kozioro\u017cec）
    "baran": "白羊座", "byk": "金牛座", "bli\u017ani\u0119ta": "双子座", "rak": "巨蟹座",
    "lew": "狮子座", "panna": "处女座", "waga": "天秤座", "skorpion": "天蝎座",
    "strzelec": "射手座", "kozioro\u017cec": "摩羯座", "wodnik": "水瓶座", "ryby": "双鱼座",
    # 法语
    "b\u00e9lier": "白羊座", "taureau": "金牛座", "g\u00e9meaux": "双子座", "vierge": "处女座",
    "sagittaire": "射手座", "capricorne": "摩羯座", "verseau": "水瓶座", "poissons": "双鱼座",
    # 德语
    "widder": "白羊座", "stier": "金牛座", "zwillinge": "双子座", "krebs": "巨蟹座",
    "l\u00f6we": "狮子座", "jungfrau": "处女座", "waage": "天秤座", "sch\u00fctze": "射手座",
    "steinbock": "摩羯座", "wassermann": "水瓶座", "fische": "双鱼座",
}

_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _build_alias_matchers():
    """中文别名用包含匹配（无词边界），其它语言用"字母边界整词"匹配。

    m06495：原来是子串匹配，外语短词会误伤（`rak` 命中 `bracket`、`lew` 命中 `new`），
    而意大利语/俄语/波兰语这些整篇都是外语，靠子串又认不准，所以按字母边界匹配。
    """
    plain, rx = [], []
    for k, v in ZODIAC_ALIASES.items():
        if _CJK_RE.search(k):
            plain.append((k, v))
        else:
            rx.append((re.compile(r"(?<![^\W\d_])%s(?![^\W\d_])" % re.escape(k), re.I), v))
    return plain, rx


_ALIAS_CJK, _ALIAS_RX = _build_alias_matchers()

TYPE_ENERGY = "energy"
TYPE_PICK = "pick"
TYPE_ALL_SIGNS = "all_signs"
TYPE_UNKNOWN = "unknown"

TYPE_LABEL = {
    TYPE_ENERGY: "能量",
    TYPE_PICK: "选组",
    TYPE_ALL_SIGNS: "全星座",
    TYPE_UNKNOWN: "待定",
}

DEFAULT_PRICE = {TYPE_ENERGY: 29, TYPE_PICK: 59, TYPE_ALL_SIGNS: 79}

# ---------------------------------------------------------------- 时间戳

_TS_RE = re.compile(r"(?<![\d:])(\d{1,2}):([0-5]\d)(?::([0-5]\d))?(?![\d:])")
_URL_RE = re.compile(r"https?://\S+")
_HASHTAG_RE = re.compile(r"#\w+")


@dataclass
class Chapter:
    name: str
    seconds: int
    raw: str = ""

    def hhmmss(self) -> str:
        # 后台既有数据一律 HH:MM:SS（不足 1 小时也补 00:），
        # 例：白羊座 — 00:02:11 / 天蝎座 — 01:49:33
        s = max(0, int(self.seconds or 0))
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return "%02d:%02d:%02d" % (h, m, s)

    def line(self) -> str:
        return "%s \u2014 %s" % (self.name, self.hhmmss())

    def to_dict(self) -> dict:
        return {"name": self.name, "seconds": self.seconds, "raw": self.raw}


def _secs(m):
    a, b, c = m.group(1), m.group(2), m.group(3)
    if c is None:
        return int(a) * 60 + int(b)
    return int(a) * 3600 + int(b) * 60 + int(c)


def _clean_name(s):
    s = _URL_RE.sub("", s)
    s = s.strip(" \t|\u00b7\u2022-\u2013\u2014:：,，.。*#>[](){}\u3000")
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"^(?:选项\s*)?\d{1,2}\s*[.、)）]\s*", "", s)
    s = re.sub(r"^(?:选项|组)\s*\d{1,2}\s*[—\-:]?\s*", "", s)
    return s.strip(" \t\u2014\u2013-\u00b7\u2022|:：")


def _norm_zodiac(name):
    s = (name or "").strip()
    if not s:
        return name
    for cn in ZODIAC_CN:
        if cn in s:
            return cn
    low = s.lower()
    for k, v in _ALIAS_CJK:
        if k in s:
            return v
    for rx, v in _ALIAS_RX:
        if rx.search(low):
            return v
    return name


def _dedupe(items):
    seen_ts = set()
    seen_name = set()
    out = []
    for c in items:
        if c.seconds in seen_ts:
            continue
        if c.name and c.name in seen_name:
            continue
        seen_ts.add(c.seconds)
        seen_name.add(c.name)
        out.append(c)
    out.sort(key=lambda c: c.seconds)
    return out


def parse_chapters(text):
    """从 description / 评论 / 章节分段框里抽取时间戳分段。

    支持三种实际出现过的写法：
      1. 白羊座 — 00:02:11      （后台 #chapter 的格式，名字在前）
      2. 00:00 The Fog Breaks   （YouTube 标准章节，时间在前）
      3. 02:11 金牛座
    """
    if not text:
        return []
    out = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line or _URL_RE.fullmatch(line):
            continue
        m = _TS_RE.search(line)
        if not m:
            continue
        before = _clean_name(line[: m.start()])
        after = _clean_name(line[m.end():])
        name = after if (not before or (len(before) <= 2 and len(after) > 2)) else before
        if not name:
            continue
        if _HASHTAG_RE.fullmatch(name):
            continue
        out.append(Chapter(name=_norm_zodiac(name), seconds=_secs(m), raw=line))
    return _dedupe(out)


def format_chapter_block(chapters, sep="\r\n"):
    """拼成后台 #chapter 需要的格式：每行 `名称 — MM:SS`，CRLF 换行。"""
    return sep.join(c.line() for c in chapters)


# ---------------------------------------------------------------- 类型判定

def zodiac_hits(chapters):
    names = set(c.name for c in chapters)
    return sum(1 for n in names if n in ZODIAC_CN)


# 用户 m03033-4：有时间戳不一定是全星座，要看标题有没有 "all sign" 之类的字样。
# 这些词出现在标题里就直接判全星座（标题是最可靠的信号，时间戳只是辅助）。
ALL_SIGNS_PAT = re.compile(
    r"all\s*signs?|all\s*star\s*signs?|all\s*12\s*signs?|every\s*sign|"
    r"all\s*zodiac|todos\s+los\s+signos|todos\s+os\s+signos|tous\s+les\s+signes|"
    r"alle\s+sternzeichen|所有星座|十二星座|全星座|全部星座",
    re.I,
)


def looks_like_all_signs(text):
    """标题级判断：是否点名"所有星座"。"""
    return bool(ALL_SIGNS_PAT.search(text or ""))


# 用户 m03155：选组看标题。这几个词是从后台 119 条 0.59 元老稿里归纳的。
PICK_PAT = re.compile(
    # m04410：用户指出选组标题常带「互动占卜」——记进信号词
    r"互动占卜|互动塔罗|互动式|选组|选一组|选一颗|选一条|选一个|选一只|选一|"
    r"无时限|无时间限制|不限时间|"
    r"\bpick\s+a\b|pick\s*your|choose\s+(a|your|one)|"
    r"se[cç]enek|opci[oó]n|op[cç][aã]o|option",
    re.I,
)


PICK_CHAPTER_PAT = re.compile(
    r"\b(?:op[cç][aã]o|opci[oó]n|option|se[cç]enek|选项|選項|pile|grupo|group)\s*[0-9一二三四五六七八九十]",
    re.I,
)


def looks_like_pick_chapters(chapters):
    """章节里有 "Opção 1 / 选项一 / Option 2 / Pile 3" 这类编号选项 -> 选组。

    这是硬证据：比标题里的 all signs 更可信（m03475：葡萄牙玫瑰标题带 All Signs，
    但章节是 Introdução + Opção 1/2，实际是选组）。
    """
    for ch in (chapters or []):
        name = getattr(ch, "name", None) or (ch.get("name") if isinstance(ch, dict) else "") or ""
        if PICK_CHAPTER_PAT.search(name):
            return True
    return False


def looks_like_pick(text):
    """标题级判断：是否是选组（互动塔罗 / 选一组 / pick a pile 之类）。"""
    return bool(PICK_PAT.search(text or ""))


def classify(chapters, duration_sec=None, title="", known_type=None):
    """判定视频属于能量 / 选组 / 全星座（用户 m03155 / m03475 的规则）。

    判断顺序：
      1. 章节里有编号选项（Opção 1 / Option 2 / 选项一 / Pile 1）-> 选组（硬证据，压过标题）
      2. 标题有 all signs / 全星座                             -> 全星座
      3. 标题有 互动塔罗 / 选一组 / pick a / 选一颗            -> 选组
      4. 章节命中 >= 10 个星座                                 -> 全星座
      5. 记忆库里该博主的历史主导类型                          -> 用它
      6. 其余                                                  -> 能量
    注意：不再返回 unknown（旧逻辑已废除）。
    """
    # 用户 m03155：废除"按时间戳个数判类型"的旧标准。
    # 全星座看标题（all signs 之类）；选组看标题（互动塔罗/选一组之类）；其余一律能量。
    # 0) 硬证据：章节里有编号选项 -> 选组（优先于标题，见 m03475）
    if looks_like_pick_chapters(chapters):
        return TYPE_PICK
    if looks_like_all_signs(title):
        return TYPE_ALL_SIGNS
    if looks_like_pick(title):
        return TYPE_PICK
    # 兜底：标题没写 all signs，但章节里凑齐 10 个以上星座，仍按全星座
    if zodiac_hits(chapters) >= 10:
        return TYPE_ALL_SIGNS
    # 记忆库：只在"有章节、但名字认不出来"时兜底（m04376 用户纠正）。
    # 完全没有时间戳的视频不能因为"这个博主一般发选组"就判成选组——
    # 那种情况它本来就是能量/口播类内容。
    if chapters and len(chapters) >= 2 and known_type in (TYPE_PICK, TYPE_ALL_SIGNS, TYPE_ENERGY):
        return known_type
    return TYPE_ENERGY


# 用户 m01172 的时长规则：能量超过 40 分钟性价比太低不更，全星座超过 4 小时不更
MAX_DURATION = {TYPE_ENERGY: _rules.duration_limit_seconds(TYPE_ENERGY),
                TYPE_ALL_SIGNS: _rules.duration_limit_seconds(TYPE_ALL_SIGNS)}


def zodiac_names_in(text):
    """返回文本里命中的星座（归一化后去重）。用于标题级判断。"""
    low = (text or "").lower()
    hit = set()
    for k, v in ZODIAC_ALIASES.items():
        if k in low:
            hit.add(v)
    return hit


def looks_like_single_sign_batch(titles):
    """用户 m01172 第 4 条：一次更新 6 个或 12 个视频、每个只讲一个星座的，不更。

    典型是「塔罗女王」这种一天发 12 条单星座的频道。
    """
    titles = [t for t in (titles or []) if t]
    if len(titles) < 6:
        return False
    single = [t for t in titles if len(zodiac_names_in(t)) == 1]
    if len(single) < 6:
        return False
    signs = set()
    for t in single:
        signs |= zodiac_names_in(t)
    # 覆盖 6 个以上不同星座 -> 明显是「一个星座一条」的分星座发法
    return len(signs) >= 6


def duration_filter(vtype, duration_sec):
    """返回丢弃原因，None 表示可以更新。"""
    limit = MAX_DURATION.get(vtype)
    if limit and duration_sec and duration_sec > limit:
        return "%s 时长 %d 分钟 > 上限 %d 分钟" % (vtype, int(duration_sec // 60), int(limit // 60))
    return None


# ---------------------------------------------------------------- 标题

_BAD_TITLE_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def clean_title(s, max_len=60):
    s = _BAD_TITLE_CHARS.sub(" ", s or "")
    s = re.sub(r"\s{2,}", " ", s).strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip() + "\u2026"
    return s


def build_title(cn_name, vtype, cn_title):
    """按后台既有规范拼标题。

    【博主】+标题               （能量）
    【博主】【全星座】+标题       （全星座 / 选组）
    """
    name = clean_title(cn_name, 30)
    title = clean_title(cn_title, 60)
    # 用户 m03155：AI 标题开头常带 [博主名]/【博主名】，拼上【博主】会重复两遍
    # 例：【约瑟夫】[约瑟夫]这里有件很讽刺的事正在发生 —— 这里把开头那个去掉
    title = strip_leading_name(title, name)
    label = TYPE_LABEL.get(vtype, "")
    if vtype in (TYPE_ALL_SIGNS, TYPE_PICK) and label:
        return "【%s】【%s】%s" % (name, label, title)
    return "【%s】%s" % (name, title)


def strip_leading_name(title, name):
    """去掉标题开头重复的博主名（带括号的、紧跟分隔符的）。"""
    if not title or not name:
        return title
    pat = re.compile(
        r"^\s*(?:[\[【（(]\s*" + re.escape(name) + r"\s*[\]】）)]\s*)+[:：\-—|｜]?\s*",
        re.I,
    )
    out = pat.sub("", title, count=1).strip()
    return out or title


def all_signs_incomplete(chapters):
    """用户 m03155：全星座的时间戳必须齐（12 个星座），不齐就先不发。"""
    return len(zodiac_hits_names(chapters)) < 12


def zodiac_hits_names(chapters):
    return set(c.name for c in chapters if c.name in ZODIAC_CN)


# ---------------------------------------------------------------- 计费

def calc_cost(file_bytes):
    """能量币费用：50KB 内 10 币，之后每 50KB +5 币。已用 5 条真实数据反算验证。"""
    if file_bytes <= 0:
        return 0
    kb = file_bytes / 1024.0
    extra = max(0.0, kb - 50.0)
    return 10 + math.ceil(extra / 50.0) * 5


# ---------------------------------------------------------------- srt 清洗

_SRT_TIME = re.compile(
    r"(\d{1,2}):([0-5]\d):([0-5]\d)[,.](\d{1,3})\s*-->\s*(\d{1,2}):([0-5]\d):([0-5]\d)[,.](\d{1,3})"
)
_INLINE_TAG = re.compile(r"<[^>]{1,60}>|\{\\[^{}]{0,40}\}")
_MUSIC_NOISE = re.compile(r"^[\[\(（【]?(音乐|music|applause|掌声|laughter|笑)[\]\)）】]?$", re.I)


def _norm_srt_time(h, m, s, ms):
    return "%02d:%s:%s,%03d" % (int(h), m, s, int(ms.ljust(3, "0")))


def _merge_cues(cues, max_len):
    """把短句合并成接近一句的长度，句子结束处强制断开。"""
    if not cues:
        return []
    merged = []
    cur_begin, cur_end, cur_text = cues[0]
    for begin, end, content in cues[1:]:
        joined = (cur_text + " " + content).strip()
        tail = cur_text.rstrip()
        boundary = tail.endswith((".", "!", "?", "\u2026", "。", "！", "？"))
        if boundary or len(joined) > max_len:
            merged.append((cur_begin, cur_end, cur_text))
            cur_begin, cur_end, cur_text = begin, end, content
        else:
            cur_end = end
            cur_text = joined
    merged.append((cur_begin, cur_end, cur_text))
    return merged


def clean_srt(text, merge=True, max_len=90):
    """清洗 YouTube 自动字幕。

    1. 去掉 <00:00:01.240>、<c>、{\\an8} 这类内联标记
    2. 丢掉纯音乐/掌声噪声块
    3. 去掉滚动字幕造成的相邻重复行
    4. 把碎成 2~5 个词的短行按句子边界合并
    """
    if not text:
        return ""
    text = text.lstrip("\ufeff")
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    cues = []
    for b in blocks:
        lines = [ln for ln in b.split("\n") if ln.strip()]
        if not lines:
            continue
        tm = _SRT_TIME.search(b)
        if not tm:
            continue
        begin = _norm_srt_time(*tm.group(1, 2, 3, 4))
        end = _norm_srt_time(*tm.group(5, 6, 7, 8))
        idx = 0
        for i, ln in enumerate(lines):
            if "-->" in ln:
                idx = i
                break
        content = " ".join(lines[idx + 1:])
        content = _INLINE_TAG.sub("", content)
        content = re.sub(r"\s{2,}", " ", content).strip()
        if not content or _MUSIC_NOISE.match(content):
            continue
        if cues and content.startswith(cues[-1][2]) and len(content) < len(cues[-1][2]) * 2:
            cues[-1] = (cues[-1][0], end, content)
            continue
        if cues and cues[-1][2] == content:
            cues[-1] = (cues[-1][0], end, content)
            continue
        cues.append((begin, end, content))

    if merge:
        cues = _merge_cues(cues, max_len)
    out = []
    for i, (begin, end, content) in enumerate(cues, 1):
        out.append("%d\n%s --> %s\n%s\n" % (i, begin, end, content))
    return "\n".join(out)


# ---------------------------------------------------------------- 杂项

def upload_date_in_window(upload_date, ws, we):
    """判断 YouTube 的 upload_date（"YYYYMMDD"，UTC 日）是否落在扫描窗口内。

    2026-11-09 的漏洞：兜底链（RSS 与频道页都取不到）会退回"频道最新 N 条"，
    那条路没有日期，把 Kitty 5 个月前的视频当成新视频捞进来（见 RULES.md §30）。
    这里用详情里的 upload_date 复核一次。

    只按"整天区间"和窗口比：视频可能在上传日的任意时刻上线，只要这一整天与窗口
    有任何交集就算在窗口内，避免跨零点的日界误伤（21:00 窗口跨两个 calendar day）。
    upload_date 认不出时放行——宁可按老逻辑处理，也不因为没有日期就把新视频丢掉。
    """
    ud = (upload_date or "").strip()
    if not (ws and we) or len(ud) != 8 or not ud.isdigit():
        return True
    try:
        import datetime as _dt
        d0 = _dt.datetime.strptime(ud, "%Y%m%d")
    except Exception:
        return True
    day_start = d0.timestamp()
    day_end = day_start + 86400
    # 整天区间与窗口完全不相交才判假
    return not (day_start >= int(we) + 86400 or day_end <= int(ws))


def sniff_srt_encoding(raw):
    """返回 (文本, 编码)。工具链产出的 srt 以 UTF-8 为主，兜底 GBK。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8-replace"


def safe_filename(name, max_len=120):
    s = _BAD_TITLE_CHARS.sub("_", name or "").strip(" .")
    s = re.sub(r"_{2,}", "_", s)
    return s[:max_len].rstrip(" .") or "untitled"

# ---------------------------------------------------------------- 候选过滤

MUSIC_HINTS = (
    "mash up", "mashup", "mash-up", "instrumental", "alt-cover", "cover",
    "official video", "lyric", "remix", "edit", "audio", "ft.", "feat.",
    "playlist", "mix ", "dj ",
)

# 正常解读视频的时长下限（秒）。实测：真解读 1379s 起，音乐类 150-290s，
# 频道里的 Shorts 时长为 0。
MIN_VIDEO_SECONDS = int(_rules.DATA.get("min_duration_minutes", 8) * 60)
MAX_VIDEO_SECONDS = 5 * 3600

# 观众付费解读类直播回放（按问题/看个人星盘收费），对我们受众没价值，不再更新。
# 用户 m05021 2026-11-06 举例【Anastasia】；实测 Anastasia streams 72/115 命中、
# Edgar streams 37/168 命中，两人普通 videos 页 0 命中（不误伤）；
# 关键词可在 rules.yaml 的 paid_live_patterns 里改。
PAID_LIVE_PATTERNS = tuple(
    _rules.DATA.get("paid_live_patterns")
    or (r"birth\s*chart\s*read", r"per\s+question", r"live\s+readings?")
)
_PAID_LIVE_RE = re.compile("|".join("(?:%s)" % p for p in PAID_LIVE_PATTERNS), re.I)


def looks_paid_live(title: str) -> str:
    """"观众付费解读"类标题，返回命中的关键词；不是这类返回空串。"""
    m = _PAID_LIVE_RE.search(title or "")
    return m.group(0) if m else ""


# 观众互动类（现场给观众/听众做解读），用户 m05854 起不再更新。
# 例：Evan "Astrologer Reads Audience Members Based on Their Big 3…"、
#     "We Did Live Astrology Readings During an Eclipse…And it Got Personal"
# 关键词可在 rules.yaml 的 viewer_interaction_patterns 里改。
VIEWER_INTERACTION_PATTERNS = tuple(
    _rules.DATA.get("viewer_interaction_patterns")
    or (r"reads?\s+(the\s+)?(audience|viewers?|subscribers?)",
        r"audience\s+(members?|readings?|questions?)")
)
_VIEWER_RE = re.compile("|".join("(?:%s)" % p for p in VIEWER_INTERACTION_PATTERNS), re.I)


def looks_viewer_interaction(title: str) -> str:
    """"观众互动"类标题，返回命中的关键词；不是这类返回空串。"""
    m = _VIEWER_RE.search(title or "")
    return m.group(0) if m else ""


def is_candidate(title: str, duration_sec, description: str = "") -> tuple[bool, str]:
    """判断一个频道条目是否值得当解读视频处理。返回 (是否, 原因)。"""
    d = duration_sec or 0
    t = (title or "").lower()
    if d == 0:
        return False, "时长 0（Shorts 或未开播）"
    hit = looks_paid_live(title)
    if hit:
        return False, "观众付费解读类（标题命中「%s」，按设定不更新）" % hit
    hit = looks_viewer_interaction(title)
    if hit:
        return False, "观众互动类（标题命中「%s」，按设定不更新）" % hit
    if d < MIN_VIDEO_SECONDS:
        return False, "时长 %ds 太短，像音乐/短片" % d
    if d > MAX_VIDEO_SECONDS:
        return False, "时长 %ds 超上限" % d
    # m06495：原来 `#tarot/#tarotreading/#lovetarot/#fyp` 一票否决，把 Kitty 那种
    # 两小时全星座（标题习惯挂 #tarot）12 条全丢了。现在只有「#shorts/#short 且
    # 时长 < 10 分钟」才算短片——两小时的回放不可能因为一个 hashtag 就是 Shorts。
    if re.search(r"#shorts?\b", t) and d < 600:
        return False, "带 Shorts 标签且时长 %d 秒" % d
    for h in MUSIC_HINTS:
        if h in t:
            # 音乐词命中但时长够长，仍可能是正常解读（标题偶尔带 cover），
            # 只是降级：有章节描述时放行
            if description and chapter_density(description) > 0:
                return True, "标题含「%s」但有时戳章节，放行" % h
            return False, "标题含音乐词「%s」" % h
    return True, "ok"


def chapter_density(description: str) -> int:
    """描述里能解析出多少段章节（0 表示没有时间戳）。"""
    try:
        return len(parse_chapters(description or ""))
    except Exception:
        return 0

# ---------------------------------------------------------------- 章节净化

_NOISE_NAMES = ("intro", "outro", "timestamps", "timestamp", "chapters",
                "inicio", "início", "introducao", "introdução", "introduction",
                "comienzo", "先看这里", "首页", "开场", "前言", "开始",)


def _is_noise(name: str) -> bool:
    n = (name or "").strip().lower().strip(":：-— ")
    if not n:
        return True
    for k in _NOISE_NAMES:
        if n == k or n.startswith(k + " ") or n.startswith(k + ":"):
            return True
    return False


def clean_chapters(chapters, vtype: str):
    """按类型清理章节，返回可直接拼进后台的列表。

    - 全星座：只保留 12 星座，保持视频里的原始先后（时间一般递增）
    - 选组：保留命名选项，去掉 Intro/Outro 这类噪声，最多 3 个
    - 能量：空列表（后台不放时间戳）
    """
    if not chapters:
        return []
    if vtype == TYPE_ENERGY:
        return []
    if vtype == TYPE_ALL_SIGNS:
        seen = set()
        out = []
        for c in chapters:
            if c.name in ZODIAC_CN and c.name not in seen:
                seen.add(c.name)
                out.append(c)
        # 星座不足 8 个时保留原始顺序的全部（避免误判导致空表）
        return out if len(out) >= 8 else [c for c in chapters if not _is_noise(c.name)]
    # 选组：先丢开场（INICIO/Introdução/首页…），再保留最多 3 个真选项。
    # m04326：原来先截 [:3] 再过滤，导致 "INICIO + OPCIÓN 1 + OPCIÓN 2" 挤掉 OPCIÓN 3。
    real = [c for c in chapters if not _is_noise(c.name)]
    # 名称里明确写着"选项/option/opción"的优先，避免把无关分段当成选项
    named = [c for c in real if PICK_CHAPTER_PAT.search(c.name or "")]
    out = named if len(named) >= 2 else real
    return out[:3]
