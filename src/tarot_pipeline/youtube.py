# -*- coding: utf-8 -*-
r"""文件简介：YouTube 侧——代理探测、频道最新视频、字幕下载。

统一走 `python -m yt_dlp` 子进程，不 import yt_dlp 的 API——
yt-dlp 内部 API 变动频繁，命令行输出才是稳定契约。
"""
from __future__ import annotations

import json
from . import paths

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

YTDLP = [sys.executable, "-m", "yt_dlp"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DEFAULT_PORTS = [7890, 7897, 10809, 1080]


class YouTubeError(RuntimeError):
    pass


def detect_proxy(ports=None, timeout: float = 8.0) -> str | None:
    """返回可用的 HTTP 代理 URL（形如 http://127.0.0.1:7890），不可用返回 None。"""
    import socket
    for port in (ports or DEFAULT_PORTS):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                pass
        except OSError:
            continue
        # 端口开着不代表能翻墙，实际访问一次 youtube 才算数
        code = _curl_status("https://www.youtube.com/generate_204", port, timeout)
        try:
            code_n = int(code)
        except (TypeError, ValueError):
            code_n = 0
        if code_n in (200, 204, 301, 302):
            return "http://127.0.0.1:%d" % port
    return None


def _curl_status(url: str, port: int, timeout: float) -> str:
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", os.devnull, "-w", "%{http_code}",
             "--max-time", str(int(timeout)), "--proxy", "http://127.0.0.1:%d" % port, url],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout + 5,
        )
        return (r.stdout or "").strip()
    except Exception:
        return "000"


@dataclass
class Video:
    video_id: str
    title: str
    duration: int | None = None
    description: str = ""
    upload_date: str = ""
    channel: str = ""
    uploader_id: str = ""       # @handle / channel_id，单视频模式靠它反查 jb.docx
    webpage_url: str = ""
    was_live: bool = False      # True = 直播回放（已结束、有 VOD）
    is_live: bool = False       # True = 正在直播

    @property
    def url(self) -> str:
        return self.webpage_url or ("https://www.youtube.com/watch?v=" + self.video_id)


def channel_url(handle: str) -> str:
    """handle / UCxxx / 完整地址 -> 频道页地址。"""
    h = (handle or "").strip()
    if h.lower().startswith("http"):
        return h
    if h.startswith("@"):
        return "https://www.youtube.com/" + h
    if h.lower().startswith("uc") and len(h) >= 20:
        return "https://www.youtube.com/channel/" + h
    return "https://www.youtube.com/@" + h.lstrip("@")


def _add_android(args: list[str]) -> list[str]:
    """给需要视频详情的调用加 android 客户端。

    背景：2026-11 起 YouTube 对未登录的数据中心 IP 直接返回
    "Sign in to confirm you're not a bot"，默认 web 客户端全军覆没；
    实测 android 客户端能正常拿到 title/duration/description/字幕。
    flat-playlist（频道列表）不需要，加了反而可能报错。
    """
    if "--flat-playlist" in args:
        return args
    out = list(args)
    for i, a in enumerate(out):
        if a == "--extractor-args" and i + 1 < len(out) and out[i + 1].startswith("youtube:"):
            if "player_client" not in out[i + 1]:
                out[i + 1] = out[i + 1] + ";player_client=android"
            return out
    return out + ["--extractor-args", "youtube:player_client=android"]


# 用 waimian 里的 Chrome 143 登录 YouTube 后，yt-dlp 可以直接读那个 profile 的 cookie。
# 为什么要它：数据中心 IP 不登录会被 "Sign in to confirm you're not a bot" 挡掉一部分视频，
# android 客户端只是缓解，带登录态才是根治（用户 m03995 选定做这件事）。
# 值为 yt-dlp 的 --cookies-from-browser 语法，例如 "chrome:F:\\path\\to\\profile"。
COOKIES_FROM_BROWSER = os.environ.get("YIJI_COOKIES_FROM_BROWSER", "")


def set_cookies_from_browser(spec: str) -> None:
    """运行时指定浏览器 cookie 来源（config 里 youtube.cookies_from_browser）。"""
    global COOKIES_FROM_BROWSER
    COOKIES_FROM_BROWSER = (spec or "").strip()


# 登录态 cookie 文件（Netscape 格式）。有它就不必用 android 客户端绕反爬，
# 而且能拿到更完整的格式/字幕列表。由 tools_export_cookies.py 从 waimian Chrome 导出。
_DEFAULT_COOKIES = os.path.join(paths.DATA_DIR, "yt-cookies.txt")
COOKIES_FILE = os.environ.get("YIJI_COOKIES_FILE", _DEFAULT_COOKIES if os.path.exists(_DEFAULT_COOKIES) else "")

# deno 装在 C:\tools\bin：yt-dlp 的 n-sig / 播放器挑战要用 JS 运行时解，
# 没有它就会报 "n challenge solving failed ... Requested format is not available"。
JS_RUNTIME_DIR = os.environ.get("JS_RUNTIME_DIR", r"C:\tools\bin")


def set_cookies_file(path: str) -> None:
    global COOKIES_FILE
    COOKIES_FILE = (path or "").strip()


def _add_cookies(args: list[str]) -> list[str]:
    """优先用 cookies 文件；退而用 --cookies-from-browser（调用方带过就别重复加）。"""
    if any(a in ("--cookies", "--cookies-from-browser") for a in args):
        return args
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        return list(args) + ["--cookies", COOKIES_FILE]
    if COOKIES_FROM_BROWSER:
        return list(args) + ["--cookies-from-browser", COOKIES_FROM_BROWSER]
    return args


def _has_js_runtime() -> bool:
    return os.path.exists(os.path.join(JS_RUNTIME_DIR, "deno.exe"))


def _add_components(args: list[str]) -> list[str]:
    """有 deno 就拉官方 EJS 挑战求解脚本（首次会下载，之后走缓存）。"""
    if "--remote-components" in args or not _has_js_runtime():
        return args
    return list(args) + ["--remote-components", "ejs:github"]


def _env() -> dict:
    env = dict(os.environ)
    env["PATH"] = JS_RUNTIME_DIR + os.pathsep + env.get("PATH", "")
    return env


def _cmd(args: list[str], tmp_holder: list | None = None, cookies: bool = True) -> tuple[list[str], dict]:
    """统一拼命令：有登录态用默认客户端 + deno 解挑战；没登录态才用 android 绕反爬。"""
    inner = list(args)
    logged_in = bool(cookies and ((COOKIES_FILE and os.path.exists(COOKIES_FILE)) or COOKIES_FROM_BROWSER))
    if logged_in:
        # 每次给一份临时副本：yt-dlp 退出时会把 cookie jar 写回文件，
        # 6 路并发同时写同一个 data\yt-cookies.txt 会互相覆盖并抛
        # "ERROR: '<路径>'"（2026-11-06 实测：天选者档案/魔女使者/MEDVSA 三条撞上）
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            import tempfile
            fd, tmp = tempfile.mkstemp(prefix="ytck-", suffix=".txt")
            with os.fdopen(fd, "wb") as fh:
                with open(COOKIES_FILE, "rb") as src:
                    fh.write(src.read())
            if tmp_holder is not None:
                tmp_holder.append(tmp)
            inner = list(inner) + ["--cookies", tmp]
        else:
            inner = _add_cookies(inner)
    else:
        # android 不支持 cookie，带登录态时 yt-dlp 会自动跳过它，所以只在没登录态时加
        inner = _add_android(inner)
    inner = _add_components(inner)
    return YTDLP + inner, _env()


def _run(args: list[str], proxy: str, timeout: int = 120, cookies: bool = True) -> str:
    holder: list = []
    cmd, env = _cmd(list(args), holder, cookies=cookies)
    if proxy:
        cmd += ["--proxy", proxy]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
    finally:
        for tmp in holder:
            try:
                os.remove(tmp)
            except OSError:
                pass
    if r.returncode != 0 and not r.stdout.strip():
        raise YouTubeError((r.stderr or "").strip()[-600:])
    return r.stdout


_FALLBACK_HINTS = ("Sign in", "not a bot", "bot", "429", "Too Many", "Requested format")


def _run_smart(args: list[str], proxy: str, timeout: int = 120) -> str:
    """先不带 cookie（android，快 3 倍），只在被反爬/限流时才带登录态重试。"""
    try:
        return _run(list(args), proxy, timeout=timeout, cookies=False)
    except Exception as e:
        msg = str(e)
        if any(k in msg for k in _FALLBACK_HINTS):
            return _run(list(args), proxy, timeout=timeout, cookies=True)
        raise


def channel_videos(handle: str, proxy: str, limit: int = 3) -> list[Video]:
    """拿频道最近 limit 个视频的元数据（含 description，时间戳就在里面）。"""
    url = channel_url(handle)
    args = ["--flat-playlist", "--playlist-end", str(limit), "--dump-json",
            "--no-warnings", "--ignore-errors", url]
    out = _run(args, proxy, timeout=90)
    vids = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            j = json.loads(line)
        except ValueError:
            continue
        vids.append(Video(
            video_id=j.get("id") or "",
            title=j.get("title") or "",
            duration=j.get("duration"),
            description=j.get("description") or "",
            upload_date=j.get("upload_date") or "",
            channel=j.get("channel") or j.get("uploader") or "",
            webpage_url=j.get("webpage_url") or (j.get("url") if str(j.get("url","")).startswith("http") else ""),
        ))
    return [v for v in vids if v.video_id]


def video_info(video_id: str, proxy: str) -> Video:
    # 视频 id 偶尔以 "-" 开头（如 -09AW0at0hM），会被 yt-dlp 当成命令行选项，
    # 统一用完整 URL 传，避免 "no such option" 报错
    target = video_id if video_id.startswith("http") else ("https://www.youtube.com/watch?v=" + video_id)
    # 快路径见 _run_smart：android 拿元数据 ~7 秒，带 cookie 走 web+deno 要 ~20 秒（2026-11-06 实测）
    out = _run_smart(["--dump-json", "--no-warnings", target], proxy, timeout=90)
    j = json.loads(out.splitlines()[0])
    return Video(
        video_id=j.get("id") or video_id,
        title=j.get("title") or "",
        duration=j.get("duration"),
        description=j.get("description") or "",
        upload_date=j.get("upload_date") or "",
        channel=j.get("channel") or j.get("uploader") or "",
        uploader_id=j.get("uploader_id") or j.get("channel_id") or "",
        webpage_url=j.get("webpage_url") or ("https://www.youtube.com/watch?v=" + video_id),
        was_live=bool(j.get("was_live")),
        is_live=bool(j.get("is_live")),
    )


def download_subs(video: Video, proxy: str, out_dir: str, sleep: float = 2.0) -> tuple[str, str] | None:
    """下载字幕，返回 (srt 路径, 语言)；没有可用字幕返回 None。

    优先级：人工 en > 自动 en > 人工 zh > 自动 zh。
    产物落在 out_dir，文件名用视频原标题（与 F 盘根目录现有 228 个文件同规则）。
    """
    os.makedirs(out_dir, exist_ok=True)
    # 文件名必须用 video_id，不能用标题：
    # 并发下载时同标题的视频会互相覆盖，且下面"按修改时间取最新"会取到别人的文件，
    # 导致多条拿到同一份字幕、服务端 file_hash 判成"重复提交"。
    vid = str(video.video_id)
    outtmpl = os.path.join(out_dir, vid + ".%(ext)s")
    args = [
        "--write-subs", "--write-auto-subs",
        # en-orig 必须显式写上：很多英语视频的自动字幕只有 en-orig 这一种，
        # 原来只写 en.* 会漏掉，结果被判成"没有可用字幕"（2026-11-06 实测）
        "--sub-langs", "en.*,en-orig,en,zh-Hans,zh-CN,zh",
        "--sub-format", "srt/vtt/best",
        "--convert-subs", "srt",
        "--skip-download",
        "--no-warnings", "--ignore-errors",
        "-o", outtmpl,
        video.url,
    ]
    if sleep:
        time.sleep(sleep)
    # 字幕接口最容易 429（同一出口 IP 短时间请求多了就限流），退避重试三次
    last_err = None
    for attempt in range(1, 4):
        try:
            _run_smart(args, proxy, timeout=180)
            last_err = None
            break
        except Exception as e:
            last_err = e
            if "429" not in str(e):
                break
            if attempt < 3:
                wait = 45 * attempt
                print("      字幕 429 限流，等 %d 秒重试（第 %d 次）" % (wait, attempt))
                time.sleep(wait)
    if last_err is not None and "429" not in str(last_err):
        raise last_err
    # 找刚才产出的 srt：按修改时间最新
    cands = []
    for name in os.listdir(out_dir):
        if not name.lower().endswith(".srt"):
            continue
        if not name.startswith(vid):
            continue
        # en-orig 是英语原始音轨的字幕，可以用；es-orig / pt-orig 等其它语种不要
        if "-orig" in name and not re.search(r"\.en-orig\.srt$", name):
            continue
        if name.endswith(".orig.srt") and not re.search(r"\.en\.orig\.srt$", name):
            continue
        full = os.path.join(out_dir, name)
        cands.append((os.path.getmtime(full), full, name))
    if not cands:
        return None
    cands.sort(reverse=True)
    _, full, name = cands[0]
    m = re.search(r"\.([a-zA-Z\-]+)\.srt$", name)
    lang = m.group(1) if m else ""
    return full, lang


# 用户 m02970：选组视频要截图当封面。规则——时间戳里没提"展示选项时间"的，
# 一律截开始第 5 秒；提到了就截它给的那个位置（由调用方传 sec）。
# ffmpeg 真实 exe 在 C:\tools\bin（PATH 里那个是 .cmd shim，yt-dlp 不认）
FFMPEG_DIR = r"C:\tools\bin"
FFMPEG_EXE = os.path.join(FFMPEG_DIR, "ffmpeg.exe")


def grab_frame(video: Video, proxy: str, out_dir: str, sec: float = 3.0,
               timeout: int = 240) -> str | None:
    """下载视频开头一小段并截第 sec 秒的一帧，返回 jpg 路径；失败返回 None。"""
    os.makedirs(out_dir, exist_ok=True)
    vid = str(video.video_id)
    clip = os.path.join(out_dir, vid + ".clip.mp4")
    if os.path.exists(clip):
        try:
            os.remove(clip)
        except OSError:
            pass
    end = int(sec) + 6
    args = [
        "--download-sections", "*0-%d" % end,
        "--force-keyframes-at-cuts",
        "--ffmpeg-location", FFMPEG_DIR,
        "-f", "mp4/best",
        "--no-warnings", "--ignore-errors",
        "-o", clip,
        video.url,
    ]
    try:
        _run(args, proxy, timeout=timeout)
    except YouTubeError:
        return None
    if not os.path.exists(clip) or os.path.getsize(clip) < 20000:
        return None
    jpg = os.path.join(out_dir, vid + ".jpg")
    if os.path.exists(jpg):
        try:
            os.remove(jpg)
        except OSError:
            pass
    cmd = [FFMPEG_EXE, "-y", "-v", "error", "-ss", "%.2f" % sec, "-i", clip,
           "-frames:v", "1", "-q:v", "2", jpg]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception:
        return None
    try:
        os.remove(clip)
    except OSError:
        pass
    return jpg if os.path.exists(jpg) and os.path.getsize(jpg) > 5000 else None


def list_subs(video_id: str, proxy: str) -> dict:
    """调试用：列出某视频有哪些字幕（语言 -> 是否自动）。"""
    try:
        out = _run(["--list-subs", "--skip-download", "--no-warnings", video_id], proxy, timeout=60)
    except YouTubeError as e:
        return {"error": str(e)[:300]}
    lines = [l for l in out.splitlines() if l.strip()]
    return {"raw": lines[:40]}

def chapters_from_comments(video_id: str, proxy: str, limit: int = 100,
                           timeout: int = 240) -> list:
    """从视频评论区（按热门排序）里找带时间戳的那条评论。

    实测：很多频道的 time stamps 只放在评论区，description 里只写
    "TIME STAMPS IN THE COMMENT SECTION"。频道主自己发的那条在热门排序下通常很靠前。
    返回 core.Chapter 列表；找不到返回 []。
    """
    from . import core  # 延迟导入，避免循环

    args = ["--skip-download", "--write-comments",
            "--extractor-args", "youtube:comment_sort=top;max_comments=%d,%d,0" % (limit, limit),
            "--no-warnings", "--dump-json",
            video_id if str(video_id).startswith("http") else ("https://www.youtube.com/watch?v=" + video_id)]
    holder: list = []
    # 先 android（快），被挡再用 cookie（见 _run_smart 注释）
    cmd, env = _cmd(list(args), holder, cookies=False)
    if proxy:
        cmd += ["--proxy", proxy]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        j = json.loads(r.stdout.splitlines()[0])
    except Exception:
        return []

    if not (j.get("comments") or []):
        return []
    best = []
    owner = (j.get("channel") or j.get("uploader") or "").lower()
    for c in (j.get("comments") or []):
        txt = c.get("text") or ""
        if len(txt) < 12:
            continue
        chs = core.parse_chapters(txt)
        if len(chs) < 2:
            continue
        # 频道主自己的评论优先
        weight = 2 if (c.get("author") or "").lower() in owner or c.get("author_is_uploader") else 1
        score = (weight, len(chs))
        if score > (best[0] if best else (0, 0)):
            best = [score, chs]
    return best[1] if best else []

