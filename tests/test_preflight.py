# -*- coding: utf-8 -*-
"""文件简介：cookie 自检的离线测试——不联网、不发消息。

用假 video_info 模拟四种情形：能取到详情 / 报登录错误 / 报视频不可用 / 没有 cookie 文件。
推送也用假的，只记录"有没有推、推了什么"。
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tarot_pipeline import preflight, youtube as yt  # noqa: E402

FAILED = []
CFG = {
    "preflight": {"enabled": True, "cookie_video_ids": ["vid-ok"]},
    "report": {"push": True, "targets": [{"type": "im", "url": "https://example.invalid"}]},
}


def case(name):
    def deco(fn):
        try:
            fn()
            print("PASS " + name)
        except Exception as e:  # noqa: BLE001
            FAILED.append(name)
            print("FAIL %s -> %r" % (name, e))
        return fn
    return deco


def _run(monkeypatch_info, cfg=CFG, cookie="dummy.txt"):
    """把 video_info 换掉，返回 (结果, 推送记录)。"""
    pushed = []
    old_info, old_cookie, old_exists, old_push = yt.video_info, yt.COOKIES_FILE, os.path.exists, preflight.rp.push
    yt.video_info = monkeypatch_info
    yt.COOKIES_FILE = cookie
    preflight.rp.push = lambda text, targets: (pushed.append(text) or (1, []))
    os.path.exists = lambda p: True
    try:
        res = preflight.check_cookie(cfg, "127.0.0.1:7890", lambda *a, **k: None)
    finally:
        yt.video_info, yt.COOKIES_FILE, os.path.exists, preflight.rp.push = old_info, old_cookie, old_exists, old_push
    return res, pushed


@case("test_cookie_ok")
def test_cookie_ok():
    res, pushed = _run(lambda vid, proxy: {"id": vid})
    assert res["status"] == "ok", res
    assert not pushed


@case("test_cookie_sign_in_alerts")
def test_cookie_sign_in_alerts():
    def boom(vid, proxy):
        raise RuntimeError("ERROR: [youtube] %s: Sign in to confirm your age. This video may be inappropriate" % vid)
    res, pushed = _run(boom)
    assert res["status"] == "bad", res
    assert pushed and "cookie" in pushed[0], pushed
    assert "Sign in" in pushed[0], pushed


@case("test_cookie_unavailable_is_unknown")
def test_cookie_unavailable_is_unknown():
    def gone(vid, proxy):
        raise RuntimeError("ERROR: [youtube] %s: Video unavailable" % vid)
    res, pushed = _run(gone)
    assert res["status"] == "unknown", res
    assert not pushed, pushed


@case("test_cookie_missing_file")
def test_cookie_missing_file():
    res, pushed = _run(lambda vid, proxy: {"id": vid}, cookie="")
    assert res["status"] == "missing", res
    assert not pushed


@case("test_cookie_disabled")
def test_cookie_disabled():
    cfg = dict(CFG, preflight={"enabled": False, "cookie_video_ids": ["x"]})
    res, pushed = _run(lambda vid, proxy: {"id": vid}, cfg=cfg)
    assert res["status"] == "disabled", res
    assert not pushed


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("%d failed" % len(FAILED))
    raise SystemExit(1 if FAILED else 0)
