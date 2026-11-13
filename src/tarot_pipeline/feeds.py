# -*- coding: utf-8 -*-
"""文件简介：频道 RSS——拿最近 15 条视频的发布时间，用来判断"24 小时内更新"。

为什么不用 yt-dlp 的 flat-playlist：那个模式下 timestamp/upload_date 全是空的，
拿不到发布时间，只能靠 state 里"没见过"判断新视频，会把几年历史都算成新的。
"""
import datetime
from . import paths

import io
import json
import os
import re
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HERE = paths.PROJECT_ROOT
CACHE = os.path.join(HERE, "data", "channels.json")


def _px(proxy):
    return {"http": proxy, "https": proxy} if proxy else None


# 法国节点的代理会先跳到 consent.youtube.com，加这个 cookie 直接放行
_COOKIE = "SOCS=CAI; CONSENT=YES+cb"


def _get(url, proxy="", timeout=25):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en",
                                   "Cookie": _COOKIE},
                     proxies=_px(proxy), timeout=timeout)
    return r


def channel_id_from_handle(handle, proxy="", timeout=25):
    """用 @handle / /channel/UCxxx 解析出 UC 开头的频道 id。失败返回空串。"""
    from .youtube import channel_url
    if re.search(r"UC[\w-]{20,24}", handle or ""):
        m = re.search(r"(UC[\w-]{20,24})", handle)
        return m.group(1) if m else ""
    url = channel_url(handle)
    try:
        r = _get(url, proxy, timeout)
    except Exception:
        return ""
    if r.status_code != 200:
        return ""
    m = re.search(r'"(?:channel_id|externalId)":"(UC[\w-]{20,24})"', r.text)
    if m:
        return m.group(1)
    m = re.search(r"/channel/(UC[\w-]{20,24})", r.text)
    return m.group(1) if m else ""


def rss_entries(channel_id, proxy="", timeout=25):
    """返回 [(video_id, published_ts, title)]，最多 15 条，按时间新到旧。"""
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + channel_id
    try:
        r = _get(url, proxy, timeout)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
        vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", e)
        pub = re.search(r"<published>(.*?)</published>", e)
        tit = re.search(r"<title>(.*?)</title>", e)
        if not (vid and pub):
            continue
        try:
            dt = datetime.datetime.strptime(pub.group(1)[:19], "%Y-%m-%dT%H:%M:%S")
            ts = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
        except ValueError:
            continue
        out.append((vid.group(1), ts, (tit.group(1) if tit else "")))
    return out


def load_cache():
    if not os.path.exists(CACHE):
        return {}
    try:
        with io.open(CACHE, encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_cache(m):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with io.open(CACHE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1, sort_keys=True)


def ensure_channel_id(cn, handle, proxy="", cache=None):
    """拿频道 id，命中缓存就不再请求。"""
    cache = cache if cache is not None else load_cache()
    got = (cache.get(cn) or {}).get("cid")
    if got:
        return got
    cid = channel_id_from_handle(handle, proxy)
    if cid:
        cache[cn] = {"handle": handle, "cid": cid}
    return cid


def daily_window(hour=21, now=None):
    """窗口固定按「日界线 hour:00」切：起点 = 前一天 hour:00，终点 = 当天 hour:00。

    用户 m03323：不管几点开始跑，窗口都是固定的「前一天的 21:00 到当天的 21:00」，
    晚跑不会把终点往后延（否则 23:00 恢复就会把 21:00~23:00 的内容算进来，
    和第二天那轮重复）。

    11-06 21:00 跑 -> [11-05 21:00, 11-06 21:00]
    11-06 23:00 跑 -> [11-05 21:00, 11-06 21:00]（同上，不因晚跑而变宽）
    11-07 10:00 跑 -> [11-05 21:00, 11-06 21:00]（还没到 11-07 21:00，仍算 11-06 那天）
    11-07 22:00 跑 -> [11-06 21:00, 11-07 21:00]（已过日界线，算 11-07 那天）
    """
    import datetime as _dt
    now = now or _dt.datetime.now()
    end = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if end > now:
        end -= _dt.timedelta(days=1)
    start = end - _dt.timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def recent_video_ids(cn, handle, proxy="", hours=24, cache=None, window=None):
    """返回 ([video_id, ...], note)。按发布时间倒序。

    window=(start_ts, end_ts) 时用固定区间，忽略 hours。
    """
    cache = cache if cache is not None else load_cache()
    cid = ensure_channel_id(cn, handle, proxy, cache)
    if not cid:
        return None, "拿不到频道 id"
    ents = rss_entries(cid, proxy)
    if not ents:
        return None, "RSS 无数据"
    if window:
        start_ts, end_ts = window
        ids = [v for v, ts, _t in ents if start_ts <= ts < end_ts]
        label = "%s~%s" % (time.strftime("%m-%d %H:%M", time.localtime(start_ts)),
                           time.strftime("%m-%d %H:%M", time.localtime(end_ts)))
        return ids, "%d 条 RSS / %d 条落在 %s" % (len(ents), len(ids), label)
    cutoff = time.time() - hours * 3600
    ids = [v for v, ts, _t in ents if ts >= cutoff]
    newest = max(ts for _v, ts, _t in ents) if ents else 0
    age_h = (time.time() - newest) / 3600 if newest else 99999
    return ids, "%d 条 RSS / %d 条在 %dh 内（最新一条 %.1f 小时前）" % (len(ents), len(ids), hours, age_h)

def recent_entries(cn, handle, proxy="", hours=24, cache=None, window=None, fill_to=3):
    """返回 ([(video_id, title), ...], note)，按发布时间倒序。

    和 recent_video_ids 的区别是保留了标题，给"按标题精彩度排序"用（m02671 ①）。
    """
    cache = cache if cache is not None else load_cache()
    cid = ensure_channel_id(cn, handle, proxy, cache)
    if not cid:
        return None, "拿不到频道 id"
    ents = rss_entries(cid, proxy)
    note_prefix = "%d 条 RSS" % len(ents) if ents else "RSS 404"
    if not ents:
        page, pnote = channel_page_entries(handle, proxy)
        now_ts = time.time()
        ents = sorted([(v, int(now_ts - age), t) for v, t, age in page if age],
                      key=lambda x: -x[1])
        note_prefix = "页面兜底 %d 条（%s）" % (len(ents), pnote)
        # 2026-11-09（用户 m06903）：很多塔罗频道把全星座做成直播，回放只挂在 /streams，
        # /videos 里看不到。只在"这一页凑不够"时再抓一路 /streams，避免每轮多 80 次请求。
        if window:
            _s, _e = window
            _have = len([1 for _v, _ts, _t in ents if _s - 21600 <= _ts < _e + 21600])
        else:
            _have = len([1 for _v, _ts, _t in ents if _ts >= time.time() - hours * 3600])
        if _have < fill_to:
            spage, snote = channel_page_entries(handle, proxy, tab="streams")
            merged = {v: (ts, t) for v, ts, t in ents}
            for v, t, age in spage:
                if not age:
                    continue
                ts = int(now_ts - age)
                if v not in merged or ts > merged[v][0]:
                    merged[v] = (ts, t)
            ents = sorted([(v, ts, t) for v, (ts, t) in merged.items()],
                          key=lambda x: -x[1])
            note_prefix += " + streams 兜底 %d 条（%s）" % (len(spage), snote)
    if not ents:
        return None, "RSS 与频道页都没数据"
    if window:
        start_ts, end_ts = window
        picked = [(v, (t or "").strip()) for v, ts, t in ents
                  if start_ts - 21600 <= ts < end_ts + 21600]
        label = "%s~%s" % (time.strftime("%m-%d %H:%M", time.localtime(start_ts)),
                           time.strftime("%m-%d %H:%M", time.localtime(end_ts)))
        return picked, "%s / %d 条落在 %s" % (note_prefix, len(picked), label)
    cutoff = time.time() - hours * 3600
    picked = [(v, (t or "").strip()) for v, ts, t in ents if ts >= cutoff]
    return picked, "%s / %d 条在 %dh 内" % (note_prefix, len(picked), hours)

_AGE_RE = re.compile(
    r"(\d+)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h|days?|d|"
    r"weeks?|w|months?|mos?|mo|years?|yrs?|yr|y|秒|分钟|分|小时|天|日|周|个月|年)\s*(?:ago|前)",
    re.I)
_AGE_UNIT = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
             "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
             "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
             "d": 86400, "day": 86400, "days": 86400,
             "w": 604800, "week": 604800, "weeks": 604800,
             "mo": 2592000, "mos": 2592000, "month": 2592000, "months": 2592000,
             "y": 31536000, "yr": 31536000, "yrs": 31536000, "year": 31536000, "years": 31536000,
             "秒": 1, "分": 60, "分钟": 60, "小时": 3600,
             "天": 86400, "日": 86400, "周": 604800, "个月": 2592000, "年": 31536000}


def parse_age(text):
    """把 YouTube 的相对时间换算成秒，认不出返回 None。

    2026-11-09（用户 m06903 反馈）：原来只认整串 "6d ago"，于是
    "Streamed 2 days ago"（直播回放）、"Premiered 9 hours ago"（首映）、
    "直播时间：3 天前"（中文界面）全被当成"不知道什么时候"，条目直接被丢掉——
    这正是 Kitty / Harmonia 这类"全星座只发直播"的频道扫不到的原因。
    现在改成在字符串里搜 "<数字><单位> ago/前"，中英文都认。
    """
    t = (text or "").strip().replace("\u00a0", " ")
    m = _AGE_RE.search(t)
    if not m:
        return None
    return int(m.group(1)) * _AGE_UNIT.get(m.group(2).lower(), 0) or None


def channel_page_entries(handle, proxy="", timeout=30, tab="videos"):
    """从频道 /videos（或 /streams）页面解析 [(video_id, title, age_seconds)]，顺序即页面顺序（新到旧）。

    2026-11-06 起 YouTube 的 /feeds/videos.xml 对所有频道返回 404（连 Google 官方频道也是），
    只能退回页面解析。页面里每条视频的 metadataParts 带相对时间（"6d ago"/"3 hours ago"），
    精度到小时，够判 24 小时窗口。

    2026-11-09：加 tab 参数。很多塔罗频道把全星座做成直播，回放只挂在 /streams，
    /videos 里根本看不到（用户 m06903 截图证实：Kitty 三条全"直播时间：N 天前"）。
    """
    from .youtube import channel_url
    url = channel_url(handle).rstrip("/") + "/" + tab.lstrip("/")
    html, err = "", ""
    for attempt in (1, 2):          # 并发下偶发超时/同意页，重试一次（m03685）
        try:
            r = _get(url, proxy, timeout)
        except Exception as e:
            err = "页面请求失败: %s" % str(e)[:60]
            time.sleep(1.5 * attempt)
            continue
        if r.status_code != 200:
            err = "页面 HTTP %s" % r.status_code
            time.sleep(1.5 * attempt)
            continue
        if "Before you continue" in r.text[:6000]:
            err = "被同意页拦截"
            time.sleep(1.5 * attempt)
            continue
        html, err = r.text, ""
        break
    if not html:
        return [], err or "页面无内容"
    out, seen = [], set()
    for mm in re.finditer(r'"contentId":"([\w-]{11})"', html):
        vid = mm.group(1)
        if vid in seen:
            continue
        # 元数据（含相对时间）可能出现在 contentId 之前也可能之后，两侧各看 4500 字
        body = html[max(0, mm.start() - 4500): mm.start() + 4500]
        age = None
        for txt in re.findall(r'"text":\{"content":"([^"]{1,24})"\}', body):
            age = parse_age(txt)
            if age is not None:
                break
        tm = re.search(r'"lockupMetadataViewModel":\{"title":\{"content":"([^"]+)"', body)
        title = tm.group(1) if tm else ""
        if not title:
            # /streams 页的版式和 /videos 不同：标题常只在无障碍标签里，
            # 形如 "✨WHO'S IN YOUR ENERGY?✨ALL SIGNS | TAROT ... 3 hours, 7 minutes"
            am = re.search(r'"accessibilityContext":\{"label":"([^"]{4,200})"', body)
            if am:
                title = re.sub(
                    r"\s+\d+\s+(?:second|minute|hour)s?(?:,\s*\d+\s+(?:second|minute|hour)s?)*\s*$",
                    "", am.group(1)).strip()
        seen.add(vid)
        out.append((vid, title, age))
    return out, "%d 条（页面）" % len(out)
