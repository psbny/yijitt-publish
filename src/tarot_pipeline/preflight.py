# -*- coding: utf-8 -*-
"""文件简介：开跑前自检。目前只检查一件事——YouTube cookie 还能不能用。

背景（2026-11-11）：cookie 是 11-06 从 waimian Chrome 导出的，过期后不会报错退出，
而是表现为"大量取详情失败 / 大面积没字幕"，跑完一轮才发现白干了。所以在这里先花
几秒拿一条已知视频试一次：能拿到详情就算 OK；报 "Sign in" 类错误就推IM 机器人提醒，
然后照常继续（可能只是个别视频受限，不该整轮停掉）。

设计约定：
- 只读、不落盘、不改 cookie；不做"自动修复"（cookie 只能人工重新扫码导出）。
- 拿不准的错误（网络抖动、视频被删）不报警，避免狼来了。
- 探测失败不影响主流程，最坏情况就是多花几秒。
"""
import os

from . import report as rp
from . import youtube as yt

# 命中这些字样说明是"登录态"问题，不是网络问题
_BAD_MARKS = (
    "sign in to confirm",
    "sign in to view",
    "please sign in",
    "login required",
    "requires payment",
    "this video is private",
    "confirm you're not a bot",
    "confirm you’re not a bot",
)

# 这些说明"cookie 有没有都拿不到"，不能据此判断 cookie 状态
_UNKNOWN_MARKS = (
    "video unavailable",
    "this video is unavailable",
    "has been removed",
    "does not exist",
    "404",
)


def _looks_bad(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _BAD_MARKS)


def _looks_unknown(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _UNKNOWN_MARKS)


def probe_ids(cfg) -> list:
    """要探测的视频 id 列表，config 里可改；默认用一条已知能取到的普通视频。"""
    pf = cfg.get("preflight") or {}
    ids = pf.get("cookie_video_ids") or []
    if isinstance(ids, str):
        ids = [i.strip() for i in ids.split(",") if i.strip()]
    return [str(i) for i in ids if i]


def check_cookie(cfg, proxy, log=print):
    """返回 dict：status = ok / missing / bad / unknown / disabled。

    status=bad 时会尝试推一条IM 机器人提醒（config 里 report.push 与 targets 都开着才推）。
    """
    pf = cfg.get("preflight") or {}
    if pf.get("enabled") is False:
        log("cookie 自检：已关闭（preflight.enabled=false）")
        return {"status": "disabled", "detail": ""}

    cookie = yt.COOKIES_FILE or ""
    if not cookie or not os.path.exists(cookie):
        log("cookie 自检：没有 cookie 文件（%s），跳过" % (cookie or "未配置"))
        return {"status": "missing", "detail": cookie}

    ids = probe_ids(cfg)
    if not ids:
        log("cookie 自检：没配 preflight.cookie_video_ids，跳过")
        return {"status": "missing", "detail": "no probe id"}

    unknown = []
    for vid in ids:
        try:
            info = yt.video_info(vid, proxy)
        except Exception as e:  # noqa: BLE001 - 任何异常都只影响自检
            msg = str(e)
            if _looks_bad(msg):
                detail = "%s：%s" % (vid, msg.strip().splitlines()[-1][:160])
                log("cookie 自检：疑似失效 -> %s" % detail)
                _alert(cfg, detail, log)
                return {"status": "bad", "detail": detail}
            if _looks_unknown(msg):
                unknown.append("%s：%s" % (vid, msg.strip().splitlines()[-1][:120]))
                continue
            unknown.append("%s：%s" % (vid, msg.strip().splitlines()[-1][:120]))
            continue
        if info:
            log("cookie 自检：正常（%s 能取到详情）" % vid)
            return {"status": "ok", "detail": vid}

    log("cookie 自检：拿不准（%s），本轮不做提醒" % "; ".join(unknown)[:200])
    return {"status": "unknown", "detail": "; ".join(unknown)[:300]}


def _alert(cfg, detail, log=print):
    """推一条提醒；推送失败只记日志，不影响主流程。"""
    rcfg = cfg.get("report") or {}
    targets = rcfg.get("targets") or []
    if not (rcfg.get("push") and targets):
        log("cookie 自检：没配推送通道，只能在日志里提醒")
        return False
    text = ("⚠ YouTube cookie 可能已失效\n\n"
            "自检结果：%s\n\n"
            "影响：本轮可能出现大面积「取详情失败 / 没字幕」。\n"
            "处理：在 waimian 的 Chrome 里重新登录 YouTube，再跑 scripts\\export_cookies.py 导出。\n"
            "（这条只是提醒，程序会照常往下跑）" % detail)
    try:
        ok, bad = rp.push(text, targets)
        log("cookie 自检：已推送提醒（成功 %d，失败 %d）" % (ok, len(bad)))
        return ok > 0
    except Exception as e:  # noqa: BLE001
        log("cookie 自检：推送失败（继续）%s" % str(e)[:120])
        return False
