# -*- coding: utf-8 -*-
r"""文件简介：主流水线——扫 YouTube 更新 -> 下字幕 -> 判类型 -> 提时间戳 -> 提交 AI 翻译 -> 排期发布。

默认 dry-run（只打印不提交）。要真正提交必须显式加 --commit。
用法：
  tarot-pipeline run                              # 全量扫描，dry-run
  tarot-pipeline run --blogger Aura --limit 1
  tarot-pipeline run --video BV...
  tarot-pipeline run --commit                     # 真提交（会扣能量币）
  tarot-pipeline run --upload-only                # 只做第一步：并发提交，第二天再发布
  tarot-pipeline run --publish-only               # 只做第二步：等 AI 完成后统一排期发布
  tarot-pipeline run --all                        # 一步到位（扫描+提交+等 AI+发布）

并发：扫频道 / 拿详情+下字幕 / 提交 / 等 AI / 发布 五个阶段各有线程池，
参数在 config.yaml 的 concurrency 段。平台 AI 允许同一账号并行跑多条，
所以提交是并发发出去、再并发等结果。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta


import yaml

from . import feeds
from . import shots
from . import bloggers as bg
from . import chapterai
from . import core
from . import rules
from . import profiles as prof
from . import proxyctl
from . import rank
from . import publish as pub
from . import schedule as sch
from . import youtube as yt
from . import paths
from . import preflight

from .translate import translate_title

HERE = paths.PROJECT_ROOT
_LOG_LOCK = threading.Lock()


def load_config(path=None):
    path = path or os.path.join(HERE, "config.yaml")
    with io.open(path, encoding="utf-8-sig") as f:
        cfg = yaml.safe_load(f)
    for k in ("state_file", "cookie_file", "work_dir", "log_dir", "srt_dir"):
        if cfg.get(k) and not os.path.isabs(cfg[k]):
            cfg[k] = os.path.join(HERE, cfg[k])
    # 窗口日界线和每博主条数也归 rules.yaml（唯一来源），覆盖进 cfg 供各函数直接用
    cfg["window_hour"] = int(rules.DATA.get("window_hour", 21))
    cfg["max_videos_per_channel"] = int(rules.DATA.get("max_videos_per_channel", 3))
    return cfg


def _conc(cfg, key, default):
    return max(1, int((cfg.get("concurrency") or {}).get(key, default)))


def load_state(cfg):
    p = cfg["state_file"]
    if os.path.exists(p):
        with io.open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    return {"videos": {}, "runs": [], "pending": []}


def save_state(cfg, state):
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = cfg["state_file"] + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cfg["state_file"])


def log(msg):
    with _LOG_LOCK:
        print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


# ------------------------------------------------------------------ 阶段1：并发扫频道

def scan_one_channel(cfg, proxy, b, done, profiles, chan_cache=None, window=None):
    """扫一个频道，返回 {blogger, fresh, keep, notes, err}。只读 profile，不写。

    window=(start_ts, end_ts) 时先用 RSS 拿"窗口内发布的视频 id"，
    再逐条取详情——没有更新的频道直接跳过，不再空扫最近 15 条。
    """
    res = {"blogger": b, "fresh": [], "keep": [], "notes": [], "err": None}
    p = profiles.get(b.cn) or {}
    if p.get("skip"):
        res["err"] = "画像里标记了不更新（%s）" % ("; ".join(p.get("notes") or [])[:60])
        return res

    if window and chan_cache is not None:
        try:
            ents, note = feeds.recent_entries(b.cn, b.handle, proxy,
                                              cache=chan_cache, window=window)
        except Exception as e:
            ents, note = None, "RSS 异常：%s" % str(e)[:60]
        if note:
            res["notes"].append(note)
        if ents is not None:
            ents = [(v, t) for v, t in ents if v not in done]
            if not ents:
                res["err"] = "窗口内无新视频"
                return res
            per = int(cfg.get("max_videos_per_channel", 3))
            # 用户 m02671 ①：多视频博主按标题精彩程度取前几个。
            # 先按标题排序，多取一倍给后面的时长/类型过滤留余量（m03649 验证发现的缺口）。
            if len(ents) > per:
                need = min(len(ents), per * 2)
                try:
                    ents = rank.rank(b.cn, ents, cfg, top=need, log=log)[:need]
                except Exception as e:
                    res["notes"].append("排序失败：%s" % str(e)[:50])
            # 2026-11-06 优化（用户 m04253）：扫描阶段不再逐条 yt-dlp 取详情。
            # 原来扫描拿一次、阶段2 又拿一次，同一条视频白跑两遍 7 秒的 yt-dlp。
            # 现在只按标题做初筛，真实时长/类型留给阶段2 的 process_one 判。
            kept = []
            for vid, ttl in ents:
                ok, why = core.is_candidate(ttl, 1200, "")
                if ok:
                    kept.append(yt.Video(video_id=vid, title=ttl, duration=None))
                else:
                    res["notes"].append("%s 标题初筛掉（%s）" % (vid, why))
            vids = kept
            res["prefiltered"] = True
        else:
            # 2026-11-09（RULES.md §30）：RSS 与频道页都取不到时，只能退回"频道最新 N 条"。
            # 这条路没有日期信息，之前把 Kitty 5 个月前的视频当成新视频捞了进来。
            # 现在只取前 max_videos_per_channel 条，剩下的交给阶段2 用详情里的
            # upload_date 复核窗口（core.upload_date_in_window），取不到日期就放行。
            try:
                vids = yt.channel_videos(b.handle, proxy, cfg["video_limit_per_channel"])
            except Exception as e:
                res["err"] = str(e)[:140]
                return res
            _per = max(1, int(cfg.get("max_videos_per_channel", 3)))
            if len(vids) > _per:
                vids = vids[:_per]
            res["notes"].append("窗口数据取不到，只按频道最新 %d 条试（阶段2 用上传日期复核）" % len(vids))
            res["unwindowed"] = True
    else:
        try:
            vids = yt.channel_videos(b.handle, proxy, cfg["video_limit_per_channel"])
        except Exception as e:
            res["err"] = str(e)[:140]
            return res

    fresh = [v for v in vids if v.video_id not in done]
    keep, dropped = [], 0
    if res.get("prefiltered"):
        # window 分支的 stub 只有标题、没有时长，已经用 is_candidate(title, 1200) 初筛过；
        # 真实时长/合格性在阶段2 的 process_one 里补判（避免同一条视频调两次 yt-dlp）
        keep = list(fresh)
    else:
        for v in fresh:
            ok, _why = core.is_candidate(v.title, v.duration, v.description)
            if ok:
                keep.append(v)
            else:
                dropped += 1
    if dropped:
        res["notes"].append("过滤掉 %d 条不合格（音乐/太短/Shorts）" % dropped)
    if fresh:
        res["notes"].append("%d 个新视频，合格 %d" % (len(fresh), len(keep)))

    if core.looks_like_single_sign_batch([v.title for v in keep]):
        before = len(keep)
        keep = [v for v in keep if len(core.zodiac_names_in(v.title)) != 1]
        res["notes"].append("识别为单星座批量发法，丢掉 %d 条" % (before - len(keep)))
        res["single_sign_batch"] = True

    res["fresh"] = fresh
    res["keep"] = keep
    return res


def _blogger_from_video(bs, v):
    """单视频模式：从 yt.Video 反查 jb.docx 里的博主，拿不到返回 ("测试", "")。

    2026-11-09：先按 yt-dlp 的 uploader_id（= @handle）精确匹配——频道名常带花字/后缀
    （"Lia Bucci ⭐️Spazio Indaco Official"、"Dr Eva Ariah - Motywacja, …"），
    按名字比怎么都会失手，标题就被写成【测试】。
    名字匹配保留三级兜底：全名相等 → 最长公共前缀 ≥5 → 文档名是频道名的一段。
    """
    def _norm(s):
        return "".join(c for c in (s or "").lower() if c.isalnum())

    up = (getattr(v, "uploader_id", "") or "").strip().rstrip("/").split("/")[-1].lstrip("@").lower()
    if up:
        for b in bs:
            bh = (b.handle or "").strip().rstrip("/").split("/")[-1].lstrip("@").lower()
            if bh and bh == up:
                return b.cn, b.handle

    ch = (v.channel or "").strip().lower()
    nch = _norm(v.channel)
    for b in bs:
        if ch and ch in ((b.name or "").strip().lower(), (b.cn or "").strip().lower()):
            return b.cn, b.handle
    best, best_len = None, 0
    for b in bs:
        for cand in ((b.name or ""), (b.cn or "")):
            n = _norm(cand)
            if not n or not nch:
                continue
            k = 0
            while k < min(len(n), len(nch)) and n[k] == nch[k]:
                k += 1
            if k >= 5 and k > best_len:
                best, best_len = b, k
    if best:
        return best.cn, best.handle
    for b in bs:
        for cand in ((b.name or ""), (b.cn or "")):
            n = _norm(cand)
            if len(n) >= 3 and nch and n in nch:
                return b.cn, b.handle
    return "测试", ""


def collect_candidates(cfg, proxy, only_blogger, only_video, state):
    """阶段1：并发扫所有频道，返回待处理 stub 列表 [{blogger, stub}]。"""
    if only_video:
        log("单视频模式：%s" % only_video)
        v = yt.video_info(only_video, proxy)
        # 按 @handle / 频道名回查 jb.docx，拿不到才退回占位名「测试」
        cn, handle = "测试", ""
        try:
            bs = [b for b in bg.load_from_docx(cfg["blogger_docx"]) if b.ok]
            cn, handle = _blogger_from_video(bs, v)
        except Exception as e:
            log("单视频模式解析博主失败：%s" % str(e)[:80])
        log("单视频博主：%s（频道 %s）" % (cn, v.channel))
        return [{"blogger": {"cn": cn, "handle": handle, "name": v.channel}, "stub": v}]

    bs = bg.load_from_docx(cfg["blogger_docx"])
    bs = [b for b in bs if b.ok]
    if only_blogger:
        key = only_blogger.lower()
        bs = [b for b in bs if key in b.cn.lower() or key in (b.name or "").lower()]
        if not bs:
            raise SystemExit("没有匹配的博主：%s" % only_blogger)

    done = state.get("videos", {})
    profiles = prof.load()
    workers = _conc(cfg, "scan_workers", 6)
    chan_cache = feeds.load_cache()
    _ws, _we = cfg.get("window_start"), cfg.get("window_end")
    if _ws and _we:
        window = (int(_ws), int(_we))
    else:
        window = feeds.daily_window(int(cfg.get("window_hour", 21)))
    log("阶段1/5 并发扫描 %d 个频道（%d 路并行）  时间窗口 %s ~ %s" % (
        len(bs), workers,
        time.strftime("%m-%d %H:%M", time.localtime(window[0])),
        time.strftime("%m-%d %H:%M", time.localtime(window[1]))))

    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_one_channel, cfg, proxy, b, done, profiles, chan_cache, window): b for b in bs}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                r = fut.result()
            except Exception as e:
                r = {"blogger": futs[fut], "fresh": [], "keep": [], "notes": [], "err": str(e)[:140]}
            b = r["blogger"]
            if r.get("err"):
                log("  [%d/%d] 跳过 %s：%s" % (i, len(bs), b.cn, r["err"]))
                continue
            if r["notes"]:
                log("  [%d/%d] %s：%s" % (i, len(bs), b.cn, "；".join(r["notes"])))
            if r.get("single_sign_batch"):
                prof.add_note(b.cn, "偶尔发单星座批量（一个星座一条），这些跳过；其他照更")
            results.append(r)

    feeds.save_cache(chan_cache)
    per_ch = int(cfg.get("max_videos_per_channel", 3))
    cap = int(cfg.get("max_videos_per_run", 999))
    stubs = []
    for r in results:
        b = r["blogger"]
        for v in r["keep"][:per_ch]:
            stubs.append({"blogger": {"cn": b.cn, "handle": b.handle, "name": b.name}, "stub": v})
    log("阶段1 完成：共扫描 %d 个频道，%d 个有窗口内新视频，%.1fs，%d 条候选（每频道最多 %d 条）"
        % (len(bs), len(results), time.time() - t0, len(stubs), per_ch))
    return stubs[:cap]

# ------------------------------------------------------------------ 阶段2：并发拿详情 + 准备

def _waiting_expired(rec, now, days, hold_days, live_days):
    """返回丢弃原因（str），None 表示继续等。

    m07968：原来用 rec["at"] 判过期，但每轮回补都会把 at 刷成当前时间，
    结果"hold 等 3 天就放弃"永远不触发。改成记 first_at（第一次进 waiting 的时间），
    过期一律按 first_at 算；没有 first_at 的老记录退回用 at。
    """
    first = rec.get("first_at") or rec.get("at") or ""
    try:
        at = datetime.strptime(first, "%Y-%m-%dT%H:%M:%S").timestamp()
    except Exception:
        at = 0.0
    if not at:
        return None
    if at < now - days * 86400:
        return "超过 %g 天" % days
    st = rec.get("status")
    if st == "hold" and at < now - hold_days * 86400:
        return "时间戳 %g 天仍不齐" % hold_days
    if st == "live_gone" and at < now - live_days * 86400:
        return "直播结束 %g 天仍无回放" % live_days
    return None


def retry_waiting(cfg, proxy, state):
    """m04769：上次"没字幕 / 直播还没开播"的，开跑前回头再抓一次。

    state["waiting"] 以前只写不读，窗口一过就永久漏掉（2026-11-06 堆了 13 条）。
    这里把它们还原成候选，走和正常视频完全一样的处理/提交链路：
    抓到字幕就正常发（提交成功后从 waiting 里删掉），还是没有就把 at 刷新、继续等。
    """
    w = state.get("waiting") or {}
    if not w:
        return []
    days = float(cfg.get("waiting_retry_days") or 20)
    cap = int(cfg.get("waiting_retry_max") or 40)
    hold_days = float(cfg.get("hold_max_days") or 3)
    live_days = float(cfg.get("live_retry_days") or 3)
    now = time.time()
    rows = []
    dropped = []
    for vid, rec in list(w.items()):
        st = rec.get("status")
        why = _waiting_expired(rec, now, days, hold_days, live_days)
        if why:
            dropped.append((vid, st, why))
            continue
        try:
            at = datetime.strptime(rec.get("first_at") or rec.get("at") or "",
                                   "%Y-%m-%dT%H:%M:%S").timestamp()
        except Exception:
            at = 0.0
        # 预告：没到开播时间就不试（省请求，也避免刷 YouTube）
        exp = rec.get("expect_at")
        if exp:
            try:
                if datetime.fromisoformat(exp).timestamp() > now:
                    continue
            except Exception:
                pass
        rows.append((at, vid, rec))
    for vid, st, why in dropped:
        w.pop(vid, None)
        log("    放弃 %s（%s）：%s" % (vid, st, why))
    if not rows:
        return []
    rows.sort()
    try:
        bs = [b for b in bg.load_from_docx(cfg["blogger_docx"]) if b.ok]
    except Exception as e:
        log("    读博主表失败，回补跳过：%s" % str(e)[:90])
        return []
    by_cn = {b.cn: b for b in bs}
    out = []
    for _at, vid, rec in rows[:cap]:
        cn = rec.get("blogger_cn") or ""
        b = by_cn.get(cn)
        if not b:
            log("    回补跳过 %s：博主【%s】已不在名单里" % (vid, cn))
            continue
        stub = yt.Video(video_id=vid, title=rec.get("title") or "",
                        webpage_url="https://www.youtube.com/watch?v=" + vid)
        out.append({"blogger": {"cn": b.cn, "handle": b.handle, "name": b.name},
                    "stub": stub, "_retry": True})
    if out:
        names = "、".join("%s/%s" % (o["blogger"]["cn"], o["stub"].video_id) for o in out[:6])
        log("回补上次没抓到的 %d 条（%s%s）" % (len(out), names, "…" if len(out) > 6 else ""))
    return out


def _dedupe_candidates(fresh, retry):
    """回补池去重（2026-11-12 修）：直播回放会同时出现在当天扫描和 waiting 里。

    保留当天扫描的那份（信息更新，阶段2 还会重新取详情），只丢掉回补池里的重复项，
    避免同一条视频在一轮里被处理两次、统计重复计数。
    返回 (去重后的回补条目, 被去掉的条数)。
    """
    seen = {c["stub"].video_id for c in fresh if c.get("stub") is not None}
    kept = [c for c in retry if c.get("stub") is None or c["stub"].video_id not in seen]
    return kept, len(retry) - len(kept)


def prejudge_signs(cfg, chs, duration, log=print):
    """判定类型之前，先让模型认章节名（m06495）。

    场景：意大利语/俄语/波兰语这类别名表里没有的写法，章节明明 12 条却一个个星座都认不出，
    以前一律落到 energy、再被"能量上限 30 分钟"丢掉（11-08 那晚 31 条就是这么没的）。
    只在「章节 ≥8、星座 <10、时长 ≥30 分、不是选组」时调用（本地免费网关约 2 秒，不花钱）。

    返回 {序号: 中文名}（name 已就地改好），没调用或没认出返回 None。
    """
    if not chs or len(chs) < 8:
        return None
    if len(core.zodiac_hits_names(chs)) >= 10:
        return None                      # 字典已经认得够多，不用问模型
    if (duration or 0) < 1800:
        return None                      # 短视频不可能是全星座
    if core.looks_like_pick_chapters(chs):
        return None                      # 选组有自己的判定，别搅和
    mapping = chapterai.normalize_signs(cfg, chs, log=log, min_signs=10)
    if not mapping:
        return None
    for i, c in enumerate(chs):
        if i in mapping:
            c.name = mapping[i]           # 只改名字，秒数不动
    log("    星座正名（预判）：认出 %d 个星座，重判类型" % len(core.zodiac_hits_names(chs)))
    return mapping


def process_one(cfg, proxy, item_in):
    """拿完整详情 -> 提章节（含评论区）-> 判类型 -> 下字幕清洗翻译。返回 item。"""
    b = item_in["blogger"]
    stub = item_in["stub"]
    vid = stub.video_id
    try:
        full = yt.video_info(vid, proxy)
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        # m04869：直播只发"回放"。yt-dlp 对预告/刚结束的直播直接报错、拿不到 live_status，
        # 所以只能按报错文本分三态（这比盲试省很多请求，报告也清楚）：
        #   预告        -> live_future，记下开播时间，到点前不试
        #   已结束无流  -> live_gone，这几天还会转好，重试 live_retry_days 天
        #   刚开播/正在播 -> live_gone 同类（流取不到），等结束后会变成回放
        # m05854：首映（Premiere）按"直播预告"同样处理 —— 报错文本是
        # "Premieres in 36 minutes / 26 hours"，到点会自己变成正常视频，记下时间再来。
        mp = re.search(r"premieres? in (\d+)\s*(day|hour|minute|second)", low)
        if mp:
            n = int(mp.group(1))
            unit = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}[mp.group(2)]
            expect = time.time() + n * unit
            return {"video_id": vid, "blogger_cn": b["cn"], "status": "live_future",
                    "reason": "首映（%d %s后开始，到点才试）" % (n, {"day": "天", "hour": "小时", "minute": "分钟", "second": "秒"}[mp.group(2)]),
                    "expect_at": datetime.fromtimestamp(expect).isoformat(timespec="seconds"),
                    "vtype": None}
        if "live event" in low:
            m = re.search(r"will begin in (\d+)\s*(day|hour|minute)", low)
            if m:
                n = int(m.group(1))
                unit = {"day": 86400, "hour": 3600, "minute": 60}[m.group(2)]
                expect = time.time() + n * unit
                return {"video_id": vid, "blogger_cn": b["cn"], "status": "live_future",
                        "reason": "直播预告（%d %s后开播，到点才试）" % (n, {"day": "天", "hour": "小时", "minute": "分钟", "second": "秒"}[m.group(2)]),
                        "expect_at": datetime.fromtimestamp(expect).isoformat(timespec="seconds"),
                        "vtype": None}
            return {"video_id": vid, "blogger_cn": b["cn"], "status": "live_gone",
                    "reason": "直播已结束但取不到流（可能还在转码）：%s" % msg[:110], "vtype": None}
        return {"video_id": vid, "blogger_cn": b["cn"], "status": "error",
                "reason": "拿详情失败：%s" % msg[:160], "vtype": None}
    # m04869：只看回放。正在直播的跳过；was_live=True 的才是回放，照常处理。
    if getattr(full, "is_live", False):
        return {"video_id": vid, "blogger_cn": b["cn"], "status": "live_now",
                "reason": "正在直播，等结束出回放再发", "vtype": None}
    # 2026-11-09（RULES.md §30）：兜底链退回"频道最新 N 条"时没有日期信息，
    # 这里用详情里的 upload_date 复核一次窗口，避免把几个月前的老视频当新的发出去。
    if not core.upload_date_in_window(getattr(full, "upload_date", ""),
                                      cfg.get("window_start"), cfg.get("window_end")):
        return {"video_id": vid, "blogger_cn": b["cn"], "status": "skip",
                "reason": "上传日期 %s 不在扫描窗口内（%s ~ %s）" % (
                    getattr(full, "upload_date", ""),
                    time.strftime("%m-%d %H:%M", time.localtime(int(cfg["window_start"]))),
                    time.strftime("%m-%d %H:%M", time.localtime(int(cfg["window_end"])))),
                "vtype": None}
    # 阶段1 只做了标题初筛，这里用真实时长/描述补判一次（音乐混音、Shorts、超长）
    ok, why = core.is_candidate(full.title, full.duration, full.description)
    if not ok:
        return {"video_id": vid, "blogger_cn": b["cn"], "status": "skip",
                "reason": "不合格：%s" % why, "vtype": None}
    chs = core.parse_chapters(full.description)
    if len(chs) < 8 and not prof.is_energy_only(b["cn"]):
        try:
            cmt = yt.chapters_from_comments(full.video_id, proxy)
            if len(cmt) > len(chs):
                log("    时间戳来自评论区（%d 条）" % len(cmt))
                chs = cmt
        except Exception as e:
            log("    读评论区失败（继续）：%s" % str(e)[:100])
    # m06495：以前只在「已经判成全星座」之后才让模型正名，于是意大利语（ARIETE/
    # TORO）、俄语（Овен/Телец）、波兰语（Waga/Skorpion）这些字典里没有的写法
    # 永远进不到判定里，长视频全被判成 energy 再被 30 分钟上限丢掉。
    # 这里在判定之前先兜一层：章节够多（≥8）、星座认不全（<10）、又是长视频（≥30 分）。
    pre_mapping = prejudge_signs(cfg, chs, full.duration, log=log)
    # m03475：把博主历史主导类型传进去做兜底（标题和章节都没信号时用）
    vtype = core.classify(chs, full.duration, getattr(full, "title", "") or "", prof.dominant(b["cn"]))
    # 用户 m03155：全星座的时间戳必须齐（12 星座），不齐就先不发，
    # 放进"和无字幕一批"等下次再抓。其它类型不受这条限制。
    if vtype == core.TYPE_ALL_SIGNS and core.all_signs_incomplete(chs):
        # m06052：章节名写法乱（SAG/CAP/AQUA/西语/emoji）导致认不全时，交给模型正名。
        # 只改名字，秒数不动；模型挂了就保持原样继续 hold。
        # 预判那一步已经问过模型就不再重复问（省时间也省钱）。
        mapping = None if pre_mapping is not None else chapterai.normalize_signs(cfg, chs, log=log)
        if mapping:
            for i, c in enumerate(chs):
                if i in mapping:
                    c.name = mapping[i]
        if core.all_signs_incomplete(chs):
            return {"video_id": vid, "blogger_cn": b["cn"], "vtype": vtype,
                    "status": "hold",
                    "reason": "全星座时间戳不全（%d/12），先不发，和无字幕一起等下次"
                              % len(core.zodiac_hits_names(chs))}
        log("    星座正名后 12/12，按全星座继续")
    why = core.duration_filter(vtype, full.duration)
    if why:
        return {"video_id": vid, "blogger_cn": b["cn"], "vtype": vtype,
                "status": "skipped", "reason": why}
    if vtype == core.TYPE_UNKNOWN:
        # 判不出类型就不提交：不知道价钱档位、也不知道标题该不该带【全星座】/【选组】
        return {"video_id": vid, "blogger_cn": b["cn"], "vtype": vtype, "status": "skipped",
                "reason": "判不出类型（抓到 %d 条时间戳、%d 分），跳过不提交，留到下次再抓" % (len(chs), full.duration // 60)}
    cand = {"blogger": b, "video": full, "chapters": chs, "vtype": vtype}
    try:
        item = prepare(cfg, cand, proxy)
    except Exception as e:
        return {"video_id": vid, "blogger_cn": b["cn"], "vtype": vtype,
                "status": "error", "reason": "准备失败：%s" % str(e)[:200]}
    item["was_live"] = bool(getattr(full, "was_live", False))
    item["is_replay"] = item["was_live"]
    return item


def prepare(cfg, cand, proxy):
    """下字幕 + 清洗 + 算标题/时间戳/费用，不提交。"""
    v = cand["video"]
    chs = cand["chapters"]
    vtype = cand["vtype"]
    resp = yt.download_subs(v, proxy, cfg["srt_dir"])
    item = {
        "video_id": v.video_id, "url": v.url, "yt_title": v.title,
        "duration": v.duration, "blogger_cn": cand["blogger"]["cn"],
        "vtype": vtype, "chapters": [c.to_dict() for c in chs],
    }
    # 选组封面：必须是**视频截图**（用户规则 m00540：选组在视频里找选项那一段截），
    # 不能拿屏幕快照目录的现成图——那是给能量/全星座用的。
    # 必须在准备阶段截：发布阶段按规则已经关代理了，那时截不到（2026-11-06 踩过）。
    if vtype == core.TYPE_PICK:
        try:
            picked = _grab_pick_cover(cfg, v.video_id, item["chapters"])
            if picked:
                item["pick_cover"] = picked
                log("    选组封面已截图：%s" % os.path.basename(picked))
        except Exception as e:
            log("    选组截图失败（继续）：%s" % str(e)[:120])
    if resp is None:
        item["status"] = "no_subs"
        item["reason"] = "没有可用字幕"
        return item
    srt_path, lang = resp
    item["srt_path"] = srt_path
    item["srt_lang"] = lang
    item["srt_size"] = os.path.getsize(srt_path)

    if cfg.get("clean_srt", True):
        raw = open(srt_path, "rb").read()
        text, enc = core.sniff_srt_encoding(raw)
        cleaned = core.clean_srt(text)
        os.makedirs(cfg["work_dir"], exist_ok=True)
        name = core.safe_filename(os.path.splitext(os.path.basename(srt_path))[0]) + ".clean.srt"
        out = os.path.join(cfg["work_dir"], name)
        with io.open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(cleaned)
        item["clean_path"] = out
        item["clean_size"] = os.path.getsize(out)
        item["enc"] = enc

    use = item.get("clean_path") or srt_path
    item["submit_size"] = os.path.getsize(use)
    item["cost"] = core.calc_cost(item["submit_size"])
    kept = core.clean_chapters(chs, vtype)
    # m04376：规则筛不干净开场名时，交给模型再挑一遍（失败就用规则结果）。
    # m04578：只在这里花钱——选组且章节多于 4 条（含开场/广告/结尾那种脏列表）。
    if vtype == core.TYPE_PICK and len(chs) > 4:
        try:
            ai_kept = chapterai.screen(cfg, cand["blogger"]["cn"], v.title or "", vtype, chs, log=log)
            if ai_kept:
                kept = ai_kept
        except Exception as e:
            log("    章节筛选异常（用规则结果）：%s" % str(e)[:90])
    item["chapters_kept"] = [c.to_dict() for c in kept]
    item["chapter_block"] = core.format_chapter_block(kept)

    cn_title = translate_title(cfg, v.title, cand["blogger"]["cn"], vtype, log)
    item["cn_title"] = cn_title
    item["submit_title"] = core.build_title(cand["blogger"]["cn"], vtype, cn_title)
    item["status"] = "ready"
    return item


# ------------------------------------------------------------------ 阶段3：提交

_SUBMIT_LOCK = threading.Lock()
_LAST_SUBMIT = [0.0]


def _wait_submit_slot(interval):
    """全局节流：保证两次提交之间至少间隔 interval 秒（跨线程生效）。"""
    if not interval or interval <= 0:
        return
    with _SUBMIT_LOCK:
        gap = time.time() - _LAST_SUBMIT[0]
        if gap < interval:
            time.sleep(interval - gap)
        _LAST_SUBMIT[0] = time.time()


def _file_md5(path):
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _adopt_running(client, item, fhash, why):
    """提交结果不明（超时/422/502/503）时，用 file_hash 反查平台是否已经建过任务。

    只接"还在跑"的任务；已经 completed/failed 的不接，免得把老文章重复发一遍。
    """
    if not fhash:
        return False
    try:
        t = client.find_by_hash(fhash)
    except Exception:
        return False
    if not t:
        return False
    st = (t.get("status") or "")
    if st in ("completed", "failed", "error"):
        return False
    tid = t.get("id")
    item["task_id"] = tid
    item["status"] = "submitted"
    item["adopted"] = True
    log("    %s，但查到平台已受理（task=%s 状态=%s），接着等出稿" % (why, tid, st))
    return True


def submit_one(cfg, client, item):
    """提交字幕给平台 AI。

    实测两个坑（2026-11-05 夜）：
      1) 短时间集中提交时平台会回 400 context deadline exceeded / 502 / 503，
         但请求其实已受理、任务已建、文章照常生成。若判成失败就不再等出稿、
         也不补封面价格，后台会留下 vis=0 的裸草稿（当晚 7 条就是这么来的）。
         所以失败后先用 file_hash 反查，接上继续等。
      2) 422/429「文件已提交过」同样要接上已有任务等出稿，不能直接跳过。
    """
    use = item.get("clean_path") or item.get("srt_path")
    c = cfg.get("concurrency") or {}
    interval = float(c.get("submit_interval", 25))
    retries = max(1, int(c.get("submit_retries", 3)))
    backoff = float(c.get("submit_backoff", 60))
    title = item["submit_title"]
    chapter = item.get("chapter_block") or ""
    try:
        fhash = _file_md5(use)
    except Exception:
        fhash = ""
    item["file_hash"] = fhash
    last = ""
    for attempt in range(1, retries + 1):
        _wait_submit_slot(interval if attempt == 1 else 0)
        try:
            j = client.submit_srt(title, chapter, use)
        except Exception as e:
            j = {"code": -1, "msg": "异常：%s" % str(e)[:160]}
        code = j.get("code")
        if code == 0:
            tid = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else None
            item["task_id"] = tid
            item["status"] = "submitted"
            log("    已提交 id=%s 扣 %s 币" % (tid, item["cost"]))
            return item
        if code in (429, 422):
            if _adopt_running(client, item, fhash, "平台说这个文件已提交过"):
                return item
            item["status"] = "duplicate"
            item["reason"] = j.get("msg") or "同一文件已提交过"
            log("    重复跳过（%s）" % item["reason"])
            return item
        last = "%s %s" % (code, j.get("msg"))
        if _adopt_running(client, item, fhash, "提交返回 %s" % code):
            return item
        if attempt < retries:
            wait = backoff * attempt
            log("    提交失败（第 %d/%d 次）：%s → %d 秒后重试" % (attempt, retries, last, wait))
            time.sleep(wait)
        else:
            item["status"] = "submit_failed"
            item["reason"] = last
            log("    提交失败（已重试 %d 次）：%s" % (retries, last))
    return item


# ------------------------------------------------------------------ 发布

def find_cover(cfg, cn):
    """在封面目录里找该博主的截图。命名约定：【中文名】.png，其次是裸名。"""
    d = cfg.get("cover_dir")
    if not d or not os.path.isdir(d):
        return None
    for name in ("【%s】.png" % cn, "【%s】.jpg" % cn, "%s.png" % cn, "%s.jpg" % cn):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    if cn:
        for f in sorted(os.listdir(d)):
            if cn in f and f.lower().endswith((".png", ".jpg", ".jpeg")):
                return os.path.join(d, f)
    return None


def _grab_pick_cover(cfg, vid, chapters=None):
    """选组没有现成封面图时截图（用户 m02970 / m03474 的规则）：
    章节里明写展示时间就截那里，否则第 5 秒。存项目临时目录，用完清理。"""
    try:
        proxy = yt.detect_proxy() or ""
        if not proxy:
            return None
        out = os.path.join(cfg["work_dir"], "shots")
        os.makedirs(out, exist_ok=True)
        sec = shots.pick_second(chapters or [])
        return shots.capture(str(vid), proxy, os.path.join(out, str(vid) + ".jpg"), second=sec)
    except Exception as e:
        log("    截图失败：%s" % str(e)[:160])
        return None


_TYPE_LABEL = {"pick": "【选组】", "all_signs": "【全星座】"}


def _ensure_title_tags(cn: str, vtype: str, title: str) -> str:
    """保证标题是 【博主】（【类型】）标题 的形状。

    m04578：前缀是用户自己加的，平台不会补；AI 改写又常把【选组】/【全星座】丢掉。
    所以这里统一补齐，缺什么补什么，不缺就不动。
    """
    t = (title or "").strip()
    if not t:
        return t
    label = _TYPE_LABEL.get(vtype or "")
    head = "【%s】" % cn if cn else ""
    # 平台 AI 有时候自己在标题前面补一遍名字（【Filho】[Filho] 这种重复就是它干的），
    # 先剥掉再补前缀，否则会出现两个名字（用户 m05021 反馈的问题）
    if cn:
        t = core.strip_leading_name(t, cn)
    # 去掉可能重复的头部
    while head and t.startswith(head + head):
        t = t[len(head):]
    if head and not t.startswith(head):
        t = head + t
    if label and label not in t:
        t = head + label + t[len(head):] if t.startswith(head) else label + t
    return t


def publish_one(cfg, client, item, slot=None):
    """把 AI 刚生成的文章补封面/价格/定时发布。"""
    post_id = item.get("post_id")
    if not post_id:
        item["status"] = "publish_failed"
        item["reason"] = "拿不到 post_id"
        return item
    vtype = item.get("vtype") or core.TYPE_ALL_SIGNS
    if slot:
        price_fen = int(slot["price"])
        ts = int(slot["ts"])
        hhmm = slot["hhmm"]
        at = slot["at"]
    else:
        price_fen = int(sch.PRICE.get(vtype, 79))
        s = cfg.get("schedule") or {}
        at = (datetime.now() + timedelta(days=int(rules.DATA.get("days_ahead", 1)))).replace(
            hour=int(s.get("hour", 16)), minute=int(s.get("minute", 15)),
            second=0, microsecond=0)
        ts = int(at.timestamp())
        hhmm = at.strftime("%H:%M")
    # 封面来源按类型分（用户规则）：选组 = 视频截图；能量/全星座 = 屏幕快照目录的现成图
    cover = None
    if vtype == core.TYPE_PICK:
        cand_cover = item.get("pick_cover")
        if cand_cover and os.path.exists(cand_cover):
            cover = cand_cover           # 准备阶段截好的（阶段5 已关代理，截不了新的）
        else:
            cover = _grab_pick_cover(cfg, item["video_id"], item.get("chapters"))
        if not cover:
            cover = find_cover(cfg, item.get("blogger_cn") or "")   # 截不到才退回目录图
    else:
        cover = find_cover(cfg, item.get("blogger_cn") or "")
    cn = item.get("blogger_cn") or ""
    try:
        detail = client.get_post(int(post_id))
        ai_title = ((detail.get("meta") or {}).get("title") or "").strip()
        base_title = ai_title or item.get("submit_title") or ""
        title = _ensure_title_tags(cn, item.get("vtype") or "", base_title) or None
        r = pub.publish(client, int(post_id), price_fen, ts,
                        cover_path=cover, visibility=10, title=title)
        item["status"] = "published"
        item["publish"] = r
        item["slot"] = hhmm
        log("    已排期 %s %s ¥%.2f 封面=%s 正文 %d 字 频道=%s" % (
            at.strftime("%Y-%m-%d"), hhmm, price_fen / 100.0,
            "有" if cover else "无", r["body_len"], r.get("series_id")))
        # 出稿后兜底：标题若还是"两个名字"（【X】[X]…），就地改回单前缀
        # 用户 m05021 2026-11-06 决定：加自动纠正
        fixed = pub.dedupe_name(r.get("title") or "")
        if fixed:
            try:
                rr = pub.retitle(client, int(post_id), fixed)
                if rr.get("ok"):
                    log("    标题纠重：%s → %s" % ((r.get("title") or "")[:36], fixed[:36]))
                    item["title_fixed"] = {"from": r.get("title") or "", "to": rr["title"]}
                    r["title"] = rr["title"]
                else:
                    log("    [warn] 标题纠重没生效，后台仍是：%s" % (rr.get("title") or "")[:60])
            except Exception as e:
                log("    [warn] 标题纠重失败：%s" % str(e)[:120])
    except Exception as e:
        item["status"] = "publish_failed"
        item["reason"] = str(e)[:300]
        log("    排期失败：%s" % item["reason"])
    return item

def ai_halt(cfg, failed):
    """平台额度不够（status=failed + pay_status=3 退款）：停更等人充值。

    只有这一种失败会暂停（用户 m03277）。400/502/503/pending 卡死都不停。
    """
    try:
        proxyctl.stop(log=log)
    except Exception:
        pass
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# 平台 AI 额度不足（已自动退款），自动更新已暂停", "",
             "时间：" + stamp,
             "现象：任务状态 failed + 支付状态退款（pay_status=3），平台侧瞬间失败", "",
             "失败的任务（共 %d 条）：" % len(failed), ""]
    for p in failed:
        lines.append("- task_id=%s  %s" % (p.get("task_id"), (p.get("submit_title") or "")[:60]))
        lines.append("  原因：%s" % (p.get("reason") or ""))
    lines += ["", "已经做的处理：",
              "- 关掉了 clash（网络代理），避免继续白跑",
              "- 在项目目录建了 PAUSE 标记，21:00 的自动更新会跳过",
              "- 同一批里已经成功出稿的照常排期发布了，没有浪费", "",
              "怎么恢复：",
              "1. 到后台「AI文章助手 → 提交历史」确认这几条是不是显示「处理失败 + 退款」",
              "2. 确认平台额度已恢复（充值到账）后，双击「恢复更新.bat」",
              "3. 告诉我一声，我把失败的这几条重新提交"]
    text = "\n".join(lines)
    for target in (os.path.join(HERE, "ALERT.md"),
                   os.path.join(os.path.expanduser("~"), "Desktop", "已暂停-看这里.txt")):
        try:
            with io.open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except Exception:
            pass
    try:
        with io.open(os.path.join(HERE, "PAUSE"), "w", encoding="utf-8", newline="\n") as f:
            f.write("paused\n")
    except Exception:
        pass
    log("!!!! 平台 AI 额度不足（已退款）%d 条，已关闭代理并暂停自动更新" % len(failed))
    log("!!!! 详情见 ALERT.md，恢复后双击「恢复更新.bat」")


# ------------------------------------------------------------------ 阶段4+5：等 AI 完成 + 排期发布

def adopt_orphans(cfg, client, hours=8, dry=False, date=None):
    """兜底：把最近生成、正文正常但没人补封面/价格/排期的裸草稿捡回来发布。

    这是"400 超时假失败"的保险丝——即使前面漏了，收尾也能把它们救回来。
    """
    from datetime import datetime as _dt, timedelta as _td
    cutoff = _dt.now() - _td(hours=hours)
    try:
        posts = client.list_all_posts(page_size=100, max_pages=4)
    except Exception as e:
        log("捡裸草稿：拉列表失败 %s" % str(e)[:120])
        return []
    cands = []
    for p in posts:
        if p.get("visibility") not in (0, None):
            continue
        st = p.get("style")
        if isinstance(st, dict) and st.get("amount"):
            continue
        if isinstance(st, str) and st.strip() not in ("", "{}"):
            continue
        try:
            when = _dt.strptime(p.get("created_on") or "", "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if when < cutoff:
            continue
        cands.append(p)
    if not cands:
        log("捡裸草稿：没有发现（近 %d 小时内）" % hours)
        return []
    log("捡裸草稿：发现 %d 条没发布的文章" % len(cands))
    items = []
    for p in cands:
        title = ((p.get("meta") or {}).get("title") or "").strip()
        cn = ""
        for _o, _c in (("\u3010", "\u3011"), ("[", "]")):
            if title.startswith(_o):
                _e = title.find(_c)
                if _e > 0:
                    cn = title[1:_e]
                    break
        vtype = core.TYPE_ENERGY
        if "\u3010\u5168\u661f\u5ea7\u3011" in title:
            vtype = core.TYPE_ALL_SIGNS
        elif "\u3010\u9009\u7ec4\u3011" in title:
            vtype = core.TYPE_PICK
        items.append({"post_id": p.get("id"), "blogger_cn": cn, "vtype": vtype,
                      "submit_title": title, "status": "ready",
                      "created_on": p.get("created_on")})
        log("  post=%s  %s  %s" % (p.get("id"), core.TYPE_LABEL.get(vtype), title[:48]))
    if dry:
        return items

    if date is None:
        date = sch.publish_date_for(datetime.now().date(),
                                    int(rules.DATA.get("days_ahead", 1)))
    try:
        occ = sch.occupied_slots(client.list_all_posts(page_size=100, max_pages=8), date)
    except Exception:
        occ = set()
    slots = sch.plan(items, date, occ)
    log("排期方案（裸草稿）%s 共 %d 条：" % (date, len(slots)))
    for s in slots:
        log("  %s  %-4s \u00a5%.2f  %s" % (s["hhmm"], core.TYPE_LABEL.get(s["vtype"], s["vtype"]),
                                        s["price"] / 100.0, (s.get("submit_title") or "")[:40]))
    pw = _conc(cfg, "publish_workers", 3)
    with ThreadPoolExecutor(max_workers=pw) as ex:
        futs = [ex.submit(publish_one, cfg, client, s, s) for s in slots]
        for f in as_completed(futs):
            f.result()
    ok = sum(1 for s in slots if s.get("status") == "published")
    log("裸草稿处理完成：%d/%d 发布成功" % (ok, len(slots)))
    return slots


def publish_pending(cfg, client, state, dry=False):
    """把 state.pending 里 waiting 的任务并发等 AI 完成，然后统一排期、并发发布。"""
    pending = state.get("pending") or []
    todo = [p for p in pending if p.get("status") == "waiting"]
    if not todo:
        log("没有待排期的文章（pending 为空或都已处理）")
        return []

    workers = _conc(cfg, "wait_workers", 8)
    timeout = int(cfg.get("ai_timeout", 1500))
    log("阶段4/5 并发等 AI 出稿：%d 条（%d 路并行，超时 %ds）" % (len(todo), workers, timeout))
    t0 = time.time()

    def wait_one(p):
        try:
            t = client.get_task(int(p["task_id"])) or {}
            if (t.get("status") or "") != "completed":
                t = client.wait_task(int(p["task_id"]), timeout=timeout, interval=15)
            return p, t, None
        except Exception as e:
            return p, None, str(e)[:200]

    ready = []
    failed = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(wait_one, p) for p in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            p, t, err = fut.result()
            name = (p.get("submit_title") or "")[:36]
            if err:
                p["status"] = "ai_failed"
                p["reason"] = err
                failed.append(p)
                log("  [%d/%d] 等待失败 %s：%s" % (i, len(todo), name, err))
                continue
            if not t.get("post_id"):
                p["status"] = "ai_incomplete"
                p["reason"] = "AI 未产出 post_id（%s）" % t.get("status")
                p["ai_status"] = t.get("status")
                p["pay_status"] = t.get("pay_status")
                # 用户 m03277：status=failed + pay_status=3(退款) 说明平台额度不够，
                # 无法自行恢复，要停下等人处理；其余失败一律不暂停。
                if t.get("status") == "failed" and int(t.get("pay_status") or 0) == 3:
                    p["platform_broke"] = True
                failed.append(p)
                log("  [%d/%d] %s" % (i, len(todo), p["reason"]))
                continue
            p["post_id"] = t.get("post_id")
            p["ai_status"] = t.get("status")
            ready.append(p)
            log("  [%d/%d] 出稿 post=%s %s" % (i, len(todo), p["post_id"], name))
    log("阶段4 完成：%d/%d 出稿，用时 %.1f 分" % (len(ready), len(todo), (time.time() - t0) / 60))
    broke = [p for p in failed if p.get("platform_broke")]
    if broke:
        ai_halt(cfg, broke)
    elif failed:
        log("阶段4 有 %d 条失败，但都不是平台额度问题，按规则不暂停（m03277）" % len(failed))

    if not ready:
        save_state(cfg, state)
        return []

    days = int(rules.DATA.get("days_ahead", 1))
    _od = cfg.get("publish_date")
    if _od:
        date = datetime.strptime(_od, "%Y-%m-%d").date()
        log("发布日（手动指定）：%s" % date)
    else:
        date = sch.publish_date_for(datetime.now().date(), days)
    try:
        posts = client.list_all_posts(page_size=100, max_pages=8)
        occ = sch.occupied_slots(posts, date)
    except Exception as e:
        log("拉已占用时段失败，按空处理：%s" % str(e)[:150])
        occ = set()
    try:
        slots = sch.plan(ready, date, occ)
    except Exception as e:
        log("排期失败：%s" % e)
        for p in ready:
            p["status"] = "schedule_failed"
            p["reason"] = str(e)[:200]
        save_state(cfg, state)
        return ready

    log("排期方案 %s 共 %d 条（已避开 %d 个已占用时段）：" % (date, len(slots), len(occ)))
    for s in slots:
        log("  %s  %-4s ¥%.2f  %s" % (s["hhmm"], core.TYPE_LABEL.get(s["vtype"], s["vtype"]),
                                      s["price"] / 100.0, (s.get("submit_title") or "")[:44]))
    if dry:
        log("（dry-run，未实际发布）")
        return slots

    pw = _conc(cfg, "publish_workers", 3)
    log("阶段5/5 并发发布（%d 路）" % pw)
    with ThreadPoolExecutor(max_workers=pw) as ex:
        futs = [ex.submit(publish_one, cfg, client, s, s) for s in slots]
        for fut in as_completed(futs):
            fut.result()
    # 把结果回写到 pending 队列，否则下一轮会把同样的文章再排一遍（2026-11-06 踩过）
    by_post = {str(p.get("post_id")): p for p in todo if p.get("post_id")}
    for s in slots:
        p = by_post.get(str(s.get("post_id")))
        if p is not None:
            p["status"] = s.get("status") or "published"
            p["slot"] = s.get("hhmm")
            p["published_on"] = str(s.get("at") or "")
    state["pending"] = [p for p in (state.get("pending") or [])
                        if p.get("status") == "waiting"]
    save_state(cfg, state)
    ok = sum(1 for s in slots if s.get("status") == "published")
    log("阶段5 完成：%d/%d 发布成功" % (ok, len(slots)))
    return slots


# ------------------------------------------------------------------ 主流程

def clean_work_start(cfg, log=print):
    """每天开工前把 work 目录整个清空（用户 m03587）。

    以前是"更新完就删"，一旦中途报错暂停、或人手动停了，残留会一直堆着。
    改成开工前先删，保证每次跑都是干净环境，也能顺手把上次卡住留下的片段清掉。
    """
    base = cfg.get("work_dir") or ""
    if not base or not os.path.isdir(base):
        os.makedirs(base, exist_ok=True) if base else None
        return 0
    n = 0
    for root, dirs, files in os.walk(base, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
                n += 1
            except Exception:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except Exception:
                pass
    for sub in ("dl", "shots", "pick"):
        try:
            os.makedirs(os.path.join(base, sub), exist_ok=True)
        except Exception:
            pass
    log("开工前清理：work 下删掉 %d 个上次残留文件" % n)
    return n


def clean_logs(cfg, log=print):
    """日志按天保留，超过 log_keep_days 的删掉（用户 m03587 的"删干净"）。"""
    import glob
    import time as _t
    d = paths.LOG_DIR
    keep = int(cfg.get("log_keep_days", 30))
    if not os.path.isdir(d):
        return 0
    cutoff = _t.time() - keep * 86400
    n = 0
    for p in glob.glob(os.path.join(d, "*")):
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
                n += 1
        except Exception:
            pass
    if n:
        log("清理旧日志：删除 %d 个（保留最近 %d 天）" % (n, keep))
    return n


def cleanup_work(cfg, log=print):
    """删掉本次更新产生的中间文件：下载的 srt、清洗版 srt、选组截图。"""
    import glob
    base = cfg.get("work_dir") or ""
    dirs = [base, os.path.join(base, "dl"), os.path.join(base, "shots")]
    n = 0
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for pat in ("*.srt", "*.png", "*.jpg", "*.jpeg"):
            for p in glob.glob(os.path.join(d, pat)):
                try:
                    os.remove(p)
                    n += 1
                except Exception:
                    pass
    if n:
        log("清理中间文件：删除 %d 个（srt / 截图）" % n)
    return n


def run(args):
    cfg = load_config(args.config)
    if not getattr(args, "no_clean", False):
        try:
            clean_work_start(cfg, log)
            clean_logs(cfg, log)
        except Exception as _e:
            log("开工清理失败（继续跑）：%s" % str(_e)[:120])
    if args.limit:
        cfg["max_videos_per_run"] = args.limit
    if getattr(args, "date", None):
        cfg["publish_date"] = args.date
    for _k, _v in (("window_start", getattr(args, "window_start", None)),
                   ("window_end", getattr(args, "window_end", None))):
        if _v:
            try:
                cfg[_k] = int(datetime.strptime(_v, "%Y-%m-%d %H:%M").timestamp())
            except Exception as e:
                log("参数 %s=%s 解析失败：%s" % (_k, _v, e))
                return 5
    state = load_state(cfg)
    state.setdefault("pending", [])

    need_client = args.commit or args.upload_only or args.publish_only or args.all
    client = None
    if need_client:
        from .backend import Client
        client = Client(cfg["cookie_file"], log=log)
        info = client.user_info()
        bal = info.get("balance", 0)
        log("登录用户：%s，余额 %d 币" % (info.get("nickname"), bal))
        if bal < cfg["min_balance"]:
            log("余额低于 %d，停止" % cfg["min_balance"])
            return 3

    if args.publish_only:
        publish_pending(cfg, client, state, dry=args.dry_run)
        return 0

    proxy = cfg.get("proxy") or yt.detect_proxy()
    if not proxy:
        log("代理不可用：请先启动 代理目录 里的翻墙脚本，再重跑。")
        return 2
    log("代理：%s" % proxy)

    # 开跑前自检 cookie：失效时推IM 机器人提醒，但照常继续（可能只是个别视频受限）
    try:
        preflight.check_cookie(cfg, proxy, log)
    except Exception as e:  # noqa: BLE001 - 自检绝不能拖垮主流程
        log("cookie 自检出错（继续）：%s" % str(e)[:120])

    t_start = time.time()
    try:
        cands = collect_candidates(cfg, proxy, args.blogger, args.video, state)
        if not args.video:                     # 单视频调试模式不掺旧账
            try:
                retry = retry_waiting(cfg, proxy, state)
                retry, dup = _dedupe_candidates(cands, retry)
                if dup:
                    log("回补去重：%d 条同时出现在当天候选里，只处理一次" % dup)
                cands = retry + cands
            except Exception as e:
                log("回补上次没抓到的失败（继续）：%s" % str(e)[:120])
    except Exception as e:
        log("收集候选失败：%s" % e)
        traceback.print_exc()
        return 4
    if not cands:
        log("没有新视频，收工")
        return 0
    if args.limit and len(cands) > args.limit:
        log("--limit %d：候选共 %d 条，只处理前 %d 条" % (args.limit, len(cands), args.limit))
        cands = cands[: args.limit]

    workers = _conc(cfg, "detail_workers", 4)
    log("阶段2/5 并发处理 %d 条（%d 路并行：拿详情/提章节/下字幕/翻标题）" % (len(cands), workers))
    items = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process_one, cfg, proxy, c): c for c in cands}
        for i, fut in enumerate(as_completed(futs), 1):
            c = futs[fut]
            try:
                it = fut.result()
            except Exception as e:
                it = {"video_id": c["stub"].video_id, "blogger_cn": c["blogger"]["cn"],
                      "status": "error", "reason": str(e)[:200]}
            it["_retry"] = bool(c.get("_retry"))
            items.append(it)
            if it.get("status") == "ready":
                log("  [%d/%d] %s%s | %s" % (i, len(cands), "回补·" if it.get("_retry") else "",
                                    it["blogger_cn"],
                                           (it.get("yt_title") or "")[:44]))
                log("        类型=%s 时长=%d分 字幕=%sKB 费用=%d币" % (
                    core.TYPE_LABEL.get(it["vtype"]), int(it["duration"] // 60),
                    it["submit_size"] // 1024, it["cost"]))
                log("        标题：%s" % it["submit_title"])
                if it.get("chapter_block"):
                    log("        时间戳：%s" % it["chapter_block"].replace("\r\n", " / ")[:160])
            else:
                log("  [%d/%d] %s | %s —— %s：%s" % (
                    i, len(cands), it.get("blogger_cn"), (it.get("video_id") or "")[:20],
                    it.get("status"), (it.get("reason") or "")[:120]))
    log("阶段2 完成：%d/%d 就绪，用时 %.1f 分" % (
        sum(1 for it in items if it.get("status") == "ready"), len(items), (time.time() - t0) / 60))

    for it in items:
        if it.get("status") == "ready":
            try:
                prof.record(it["blogger_cn"], it["vtype"], int(it.get("duration") or 0),
                            bool(it.get("was_live")))
            except Exception as e:
                log("    写画像失败（忽略）：%s" % str(e)[:80])

    ready = [it for it in items if it.get("status") == "ready"]
    if ready and (args.commit or args.upload_only or args.all):
        sw = _conc(cfg, "submit_workers", 4)
        log("阶段3/5 并发提交 %d 条（%d 路并行）" % (len(ready), sw))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=sw) as ex:
            futs = [ex.submit(submit_one, cfg, client, it) for it in ready]
            for fut in as_completed(futs):
                fut.result()
        for it in ready:
            if it.get("task_id"):
                state.setdefault("waiting", {}).pop(it["video_id"], None)
                state["pending"].append({
                    "task_id": it["task_id"], "video_id": it["video_id"],
                    "blogger_cn": it["blogger_cn"], "vtype": it["vtype"],
                    "submit_title": it["submit_title"],
                    "srt_path": it.get("clean_path") or it.get("srt_path"),
                    "cost": it.get("cost"), "status": "waiting",
                    "chapters": it.get("chapters"),
                    "pick_cover": it.get("pick_cover"),
                    "submitted_at": datetime.now().isoformat(timespec="seconds"),
                })
        save_state(cfg, state)
        log("阶段3 完成：%d/%d 提交成功，用时 %.1f 秒" % (
            sum(1 for it in ready if it.get("task_id")), len(ready), time.time() - t0))

    if cfg.get("proxy_auto_stop", True) and proxyctl.is_running():
        log("上传部分完成，关闭网络代理（下次开跑会自动挂上）")
        proxyctl.stop(log=log)

    if args.all and client:
        publish_pending(cfg, client, state)

    run_record = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "mode": "all" if args.all else ("upload" if args.upload_only else ("commit" if args.commit else "dry-run")),
        "total": len(items),
        "elapsed_sec": round(time.time() - t_start, 1),
        "results": [{k: v for k, v in it.items() if k != "chapters"} for it in items],
    }
    state.setdefault("runs", []).append(run_record)
    for it in items:
        if it.get("status") in ("hold", "no_subs", "live_wait", "live_future", "live_gone", "submit_failed"):
            # 这两类下次要重抓：不进 videos（否则会被当成已处理），只进 waiting 备查
            _prev = (state.get("waiting") or {}).get(it["video_id"]) or {}
            state.setdefault("waiting", {})[it["video_id"]] = {
                "at": run_record["at"], "status": it["status"],
                "first_at": _prev.get("first_at") or run_record["at"],
                "blogger_cn": it.get("blogger_cn"), "vtype": it.get("vtype"),
                "reason": it.get("reason"), "title": it.get("yt_title") or _prev.get("title"),
                "expect_at": it.get("expect_at") or _prev.get("expect_at"),
                "tries": int(_prev.get("tries") or 0) + 1,
            }
        if it.get("status") in ("submitted", "published", "duplicate", "ai_incomplete"):
            state["videos"][it["video_id"]] = {
                "at": run_record["at"], "status": it["status"],
                "task_id": it.get("task_id"), "post_id": it.get("post_id"),
            }
    save_state(cfg, state)

    out = os.path.join(HERE, "logs", "run-%s.json" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(run_record, f, ensure_ascii=False, indent=2)

    ok = sum(1 for it in items if it.get("status") in ("ready", "submitted", "published"))
    log("全部完成：%d 条就绪/已提交，%d 条跳过/失败，总用时 %.1f 分" % (
        ok, len(items) - ok, (time.time() - t_start) / 60))
    log("报告：%s" % out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tarot-pipeline run")
    ap.add_argument("--config", default=None)
    ap.add_argument("--blogger", default=None, help="只跑某个博主（中文名或英文名子串）")
    ap.add_argument("--video", default=None, help="只跑单个视频 id 或 URL")
    ap.add_argument("--limit", type=int, default=None, help="本次最多处理几条")
    ap.add_argument("--commit", action="store_true", help="真正提交（默认 dry-run）")
    ap.add_argument("--upload-only", action="store_true",
                    help="只做第一步：并发提交 srt 让 AI 生成文章，不排期")
    ap.add_argument("--publish-only", action="store_true",
                    help="只做第二步：把已提交的任务等 AI 完成后统一排期发布")
    ap.add_argument("--all", action="store_true",
                    help="一步到位：扫描+提交+等 AI+排期发布（隐含 --commit）")
    ap.add_argument("--publish", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--dry-run", action="store_true",
                    help="配合 --publish-only 只打印排期方案，不真发布")
    ap.add_argument("--adopt-orphans", type=float, default=None, metavar="HOURS",
                    help="把最近 HOURS 小时内生成的裸草稿补上封面/价格/排期")
    ap.add_argument("--window-start", default=None,
                    help="自定义窗口起点 YYYY-MM-DD HH:MM（默认昨天 window_hour 点）")
    ap.add_argument("--window-end", default=None,
                    help="自定义窗口终点 YYYY-MM-DD HH:MM（默认现在）")
    ap.add_argument("--date", default=None, help="指定发布日 YYYY-MM-DD")
    ap.add_argument("--no-clean", action="store_true",
                    help="开工前不清空 work 目录（调试用）")
    args = ap.parse_args(argv)
    if args.adopt_orphans:
        cfg = load_config(args.config)
        from .backend import Client
        cl = Client(cfg["cookie_file"], log=log)
        info = cl.user_info()
        log("登录用户：%s，余额 %d 币" % (info.get("nickname"), info.get("balance", 0)))
        d = args.date
        if d:
            from datetime import datetime as _dt
            d = _dt.strptime(d, "%Y-%m-%d").date()
        adopt_orphans(cfg, cl, hours=args.adopt_orphans, dry=args.dry_run, date=d)
        return 0
    if args.upload_only or args.all:
        args.commit = True
    if getattr(args, "publish", False):
        args.all = True
        args.commit = True
    try:
        return run(args)
    finally:
        try:
            if proxyctl.is_running():
                proxyctl.stop(log=log)
        except Exception:
            pass
        # 用户 m03587：不再"跑完就删"，work 里的东西留着，下次开工前统一清，
        # 这样中途报错/暂停时还能回头看现场。


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())