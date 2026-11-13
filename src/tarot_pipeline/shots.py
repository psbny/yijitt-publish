# -*- coding: utf-8 -*-
"""文件简介：选组封面截图。

用户 m02970 / m03474 的规则：
  1. 先看章节里有没有明确写出"展示选项"的时间，有就截那里
  2. 没有就截视频第 5 秒
两种本质是同一件事（东西还在桌上），只是有的展示很短，必须靠时间戳定位。
截图只存 work/shots/ 下，下一次运行开工时由 clean_work_start 统一清空（m03475 / m03587）。
"""
import os
import re
import subprocess
import sys
import tempfile

FFMPEG_DIR = r"C:\tools\bin"
# m04326：用户实测第 5 秒太靠后（有的视频开头就切画面了），改 3 秒
DEFAULT_SECOND = 3

# 章节里明写"展示/显示"的才用它的时间，避免把 Opção 1 本身当成展示点
_SHOW_PAT = re.compile(r"展示|显示|showing|display|items?\s+shown|the\s+options?", re.I)


def pick_second(chapters):
    """决定截第几秒。章节里明写展示时间的优先，否则第 5 秒。"""
    for ch in (chapters or []):
        if isinstance(ch, dict):
            name = ch.get("name") or ""
            sec = int(ch.get("seconds", 0) or 0)
        else:
            name = getattr(ch, "name", "") or ""
            sec = int(getattr(ch, "seconds", 0) or 0)
        if sec > 0 and _SHOW_PAT.search(name):
            return sec
    return DEFAULT_SECOND


def capture(video_id, proxy, out_path, second=DEFAULT_SECOND, log=print):
    """下载视频开头几秒并截一帧。返回 out_path，失败抛异常。"""
    sec = max(1, int(second))
    tmpdir = tempfile.mkdtemp(prefix="pick_")
    tmpl = os.path.join(tmpdir, "v.%(ext)s")
    cmd = [sys.executable, "-m", "yt_dlp",
           "-f", "best[height<=720]/best",
           "--no-playlist", "--no-warnings", "--quiet",
           "--ffmpeg-location", FFMPEG_DIR,
           "--download-sections", "*0-%d" % (sec + 6),
           "--force-keyframes-at-cuts",
           "--extractor-args", "youtube:player_client=android",
           "-o", tmpl]
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append("https://www.youtube.com/watch?v=" + video_id)
    r1 = subprocess.run(cmd, capture_output=True, text=True, timeout=240,
                        encoding="utf-8", errors="replace")
    files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)] if os.path.isdir(tmpdir) else []
    if not files:
        raise RuntimeError("下载失败 %s：%s" % (video_id, (r1.stderr or r1.stdout or "")[-400:]))
    src = files[0]
    ff = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
    if not os.path.exists(ff):
        ff = "ffmpeg"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    subprocess.run([ff, "-y", "-v", "error", "-ss", str(sec), "-i", src,
                    "-frames:v", "1", "-q:v", "2", "-vf", "scale=720:-1", out_path],
                   capture_output=True, text=True, timeout=120,
                   encoding="utf-8", errors="replace")
    for f in files:
        try:
            os.remove(f)
        except Exception:
            pass
    try:
        os.rmdir(tmpdir)
    except Exception:
        pass
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 3000:
        raise RuntimeError("截图失败 %s" % video_id)
    log("    选组截图：第 %d 秒 -> %s（%.0f KB）"
        % (sec, os.path.basename(out_path), os.path.getsize(out_path) / 1024))
    return out_path