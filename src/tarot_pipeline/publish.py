# -*- coding: utf-8 -*-
"""文件简介：把 AI 生成的文章补全成可定时发布的成品。

2026-11-04 实测记录（很关键，别再踩）：
- 真正可用的 upsert body 只有 12 个字段，多传 meta/contents 之类反而会把正文写空。
  实测 payload（从浏览器 Network 抓到的原样）：
    {"id":1080095652,"visibility":0,"title":"...",
     "content":"<p>...</p>",
     "cover":"https://...png/low","tags":[1],
     "isPaid":false,"feeAmount":1,"isPublished":false,"audio":"",
     "published_on":1793866500,
     "style":"{\"amount\":79,\"show\":\"pay\",\"scheduled_at\":1793866500}"}
- published_on 必须是 int64（unix 秒）；传 "2026-11-05 16:15:00" 这种字符串会报
  "json: cannot unmarshal string into Go struct field TarotPostReq.published_on of type int64"。
- 正文只认 content 字符串。传空字符串（或提取失败）会把正文清空，所以这里强制校验长度。
- style 是 JSON 字符串，amount 单位是「分」（79 = ¥0.79）。
- visibility：0=草稿，10=定时发布，90=已发布。实测「退回草稿」必须同时把
  published_on 置 0，只改 visibility 不生效。
- 封面走 POST /api/tool/upload，返回扁平 {"name","status","url"}。
- 频道不用传：upsert 后前端会再调 /api/post/series/post 按标题前缀挂频道；
  我们直接复用详情里已有的 series_id 即可，没有就靠标题前缀让后台自己匹配。
"""
import json
import re
from datetime import datetime

from .backend import BackendError


_DUP_NAME_RE = re.compile(r"^【([^】]+)】\s*[\[\(（【]\s*([^\]\)）】]{1,20}?)\s*[\]\)）】]\s*")


def dedupe_name(title: str) -> str:
    """把"两个名字"的标题改回一个：`【Filho】[Filho]xxx` → `【Filho】xxx`。

    不是重复就返回空串，调用方据此判断要不要改（用户 m05021 2026-11-06 要求加这个）。
    成因：平台 AI 生成正文标题时会自己补一遍 `[博主名]`，我们再补【博主】前缀就成了两个。
    """
    t = (title or "").strip()
    m = _DUP_NAME_RE.match(t)
    if not m:
        return ""
    a, b = m.group(1).strip(), m.group(2).strip()
    if a.casefold() != b.casefold():
        return ""
    rest = t[m.end():].strip()
    if not rest:
        return ""
    return "【%s】%s" % (a, rest)


def _ts_of(text: str) -> int:
    """后台时间字符串 "2026-11-07 17:05:00" → unix 秒（本地时区）。"""
    try:
        return int(datetime.strptime(str(text or "").strip(), "%Y-%m-%d %H:%M:%S").timestamp())
    except Exception:
        return 0


def extract_content(detail: dict) -> str:
    """从 detail.contents 里取正文 HTML（type==9）。"""
    for c in (detail.get("contents") or []):
        try:
            if int(c.get("type") or 0) == 9:
                return str(c.get("content") or "")
        except (TypeError, ValueError):
            continue
    return ""


def build_body(detail: dict, price_fen: int, publish_at: int,
               cover_url: str = None, visibility: int = 10,
               title: str = None, content: str = None,
               tags: list = None, audio: str = "") -> dict:
    """按实测的 12 字段结构构造 upsert body。"""
    meta = detail.get("meta") or {}
    body_html = content if content is not None else extract_content(detail)
    # v2 (m03413)：小程序展示封面靠正文首图的 <img>，meta.cover 只用于列表/分享。
    # 老文章（用户手动发的）正文开头都是 <p><img src=".../low"></p><p><br></p>。
    _cover_for_img = cover_url or meta.get("cover") or ""
    if _cover_for_img and "<img" not in body_html[:400]:
        body_html = '<p><img src="%s"></p><p><br></p>' % _cover_for_img + body_html
    if len(body_html) < 200:
        raise BackendError("正文太短（%d 字），拒绝写入以免清空文章 %s" % (len(body_html), detail.get("id")))

    tag_list = tags
    if tag_list is None:
        pc = meta.get("post_category")
        tag_list = [int(pc)] if pc else [1]

    cover = cover_url or meta.get("cover") or ""
    return {
        "id": int(detail.get("id") or 0),
        "visibility": int(visibility),
        "title": title or meta.get("title") or "",
        "content": body_html,
        "cover": cover,
        "tags": [int(t) for t in tag_list],
        "isPaid": False,
        "feeAmount": 1,
        "isPublished": bool(int(visibility) == 90),
        "audio": audio,
        "published_on": int(publish_at),
        "style": json.dumps({
            "amount": int(price_fen),
            "show": "pay",
            "scheduled_at": int(publish_at),
        }, ensure_ascii=False),
    }


def publish(client, post_id: int, price_fen: int, publish_at: int,
            cover_path: str = None, visibility: int = 10,
            title: str = None, content: str = None,
            tags: list = None, audio: str = "") -> dict:
    """给 AI 生成的文章补封面/价格/定时发布。返回回读校验结果。"""
    detail = client.get_post(int(post_id))
    if not detail:
        raise BackendError("文章 %s 取不到 detail" % post_id)

    before_len = len(extract_content(detail))
    cover_url = client.upload(cover_path) if cover_path else None
    body = build_body(detail, price_fen, publish_at, cover_url, visibility,
                      title, content, tags, audio)

    j = client.upsert_post(body)
    if j.get("code") != 0:
        raise BackendError("upsert 失败：%s" % (j.get("msg") or j))

    # 挂频道：upsert 本身不处理频道，前端保存后也是单独调一次
    after0 = client.get_post(int(post_id))
    if not (after0.get("series_post") or {}).get("series_id"):
        sid = client.resolve_series_id(body.get("title") or "")
        if sid:
            try:
                client.attach_series(int(post_id), sid, "add")
            except Exception as e:
                print("  [warn] 挂频道失败：%s" % e, flush=True)

    after = client.get_post(int(post_id))
    body_len = len(extract_content(after))
    if body_len < max(200, before_len // 2):
        raise BackendError("upsert 后正文异常（%d -> %d），文章 %s 需要人工检查"
                          % (before_len, body_len, post_id))
    meta_after = after.get("meta") or {}
    return {
        "post_id": int(post_id),
        "title": meta_after.get("title") or "",
        "body_len": body_len,
        "style": after.get("style"),
        "visibility": after.get("visibility"),
        "published_on": after.get("published_on"),
        "cover": (meta_after.get("cover") or "")[:80],
        "series_id": (after.get("series_post") or {}).get("series_id"),
    }


def retitle(client, post_id: int, new_title: str) -> dict:
    """只改标题：正文/封面/价格/定时/可见性原样带回去（upsert 必须带正文，否则清空）。

    用场景：平台 AI 把名字补成两遍之后，出稿后纠正回单前缀（用户 m05021 决定）。
    返回 {ok: 是否已变成新标题, title, body_len, before_len}。
    """
    detail = client.get_post(int(post_id))
    if not detail:
        raise BackendError("文章 %s 取不到 detail" % post_id)
    try:
        style = json.loads(detail.get("style") or "{}")
    except Exception:
        style = {}
    price_fen = int(style.get("amount") or 0) or 29
    ts = int(style.get("scheduled_at") or 0) or _ts_of(detail.get("published_on"))
    vis = int(detail.get("visibility") if detail.get("visibility") is not None else 10)
    before = len(extract_content(detail))
    body = build_body(detail, price_fen, ts, None, vis, new_title, None, None, "")
    j = client.upsert_post(body)
    if j.get("code") != 0:
        raise BackendError("改标题失败：%s" % (j.get("msg") or j))
    after = client.get_post(int(post_id))
    ttl = ((after.get("meta") or {}).get("title") or "").strip()
    return {"post_id": int(post_id), "ok": ttl == (new_title or "").strip(),
            "title": ttl, "body_len": len(extract_content(after)), "before_len": before}
