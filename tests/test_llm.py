# -*- coding: utf-8 -*-
"""文件简介：本地网关链（m07729）的离线单测。

不起网络：把 `llm.requests.post` 换成假响应，验证
①第一个网关失败（HTTP 500 / 空正文）时自动换下一个；
②全失败抛 `LLMError`，错误信息里带每个网关的名字；
③没有 key 的网关被跳过；④一个网关都没配时直接抛错。

运行：python -m pytest tests -q   或   python tests/test_llm.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tarot_pipeline import llm

MSGS = [{"role": "user", "content": "hi"}]


class _Resp:
    def __init__(self, status, text="", content=None):
        self.status_code = status
        self.text = text
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _cfg():
    return {
        "llm": {
            "providers": [
                {"name": "网关A", "model": "a-model", "base": "http://127.0.0.1:9/v1", "key_env": "TEST_KEY_A"},
                {"name": "网关B", "model": "b-model", "base": "http://127.0.0.1:9/v1", "key_env": "TEST_KEY_B"},
            ]
        }
    }


def _patch_post(handler):
    calls = []

    def fake_post(url, headers=None, data=None, timeout=None, proxies=None):
        calls.append({"url": url, "headers": headers, "timeout": timeout, "proxies": proxies})
        return handler(url, data)

    llm.requests.post = fake_post
    return calls


def _restore():
    import importlib
    importlib.reload(llm)


def test_fallback_to_next_provider():
    os.environ["TEST_KEY_A"] = "ka"
    os.environ["TEST_KEY_B"] = "kb"
    logs = []

    def handler(url, data):
        s = data.decode("utf-8") if isinstance(data, bytes) else (data or "")
        if '"a-model"' in s:
            return _Resp(500, '{"error":"boom"}')
        return _Resp(200, content=" 好的 ")

    _patch_post(handler)
    txt, name = llm.chat(_cfg(), MSGS, log=lambda *a: logs.append(a[0]))
    assert txt == "好的" and name == "网关B"
    assert any("换下一个" in s for s in logs), logs
    _restore()


def test_empty_content_falls_back():
    os.environ["TEST_KEY_A"] = "ka"
    os.environ["TEST_KEY_B"] = "kb"

    def handler(url, data):
        s = data.decode("utf-8") if isinstance(data, bytes) else (data or "")
        if '"a-model"' in s:
            return _Resp(200, content="   ")
        return _Resp(200, content="第二个给的")

    _patch_post(handler)
    txt, name = llm.chat(_cfg(), MSGS, log=lambda *a: None)
    assert txt == "第二个给的" and name == "网关B"
    _restore()


def test_all_fail_raises_with_names():
    os.environ["TEST_KEY_A"] = "ka"
    os.environ["TEST_KEY_B"] = "kb"

    def handler(url, data):
        return _Resp(502, "bad gateway")

    _patch_post(handler)
    try:
        llm.chat(_cfg(), MSGS, log=lambda *a: None)
    except llm.LLMError as e:
        assert "网关A" in str(e) and "网关B" in str(e), str(e)
        assert "502" in str(e), str(e)
    else:
        raise AssertionError("全失败时应该抛 LLMError")
    _restore()


def test_missing_key_is_skipped():
    os.environ.pop("TEST_KEY_A", None)
    os.environ["TEST_KEY_B"] = "kb"
    llm.read_env_value = lambda *a, **kw: ""      # 模拟 .env 里也没有

    def handler(url, data):
        return _Resp(200, content="只有B")

    calls = _patch_post(handler)
    txt, name = llm.chat(_cfg(), MSGS, log=lambda *a: None)
    assert name == "网关B" and txt == "只有B"
    assert len(calls) == 1, "缺 key 的网关不该发请求"
    _restore()
    os.environ.pop("TEST_KEY_B", None)


def test_no_providers_raises():
    try:
        llm.chat({"llm": {"providers": []}}, MSGS, log=lambda *a: None)
    except llm.LLMError as e:
        assert "没有可用网关" in str(e), str(e)
    else:
        raise AssertionError("没配网关时应该抛 LLMError")
    _restore()


def test_local_base_never_uses_proxy():
    os.environ["TEST_KEY_A"] = "ka"
    os.environ["TEST_KEY_B"] = "kb"

    def handler(url, data):
        return _Resp(200, content="ok")

    calls = _patch_post(handler)
    llm.chat(_cfg(), MSGS, log=lambda *a: None)
    assert calls and calls[0]["proxies"] is None, calls[0]
    _restore()


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, "->", type(e).__name__, e)
    print("\n%d failed" % fails)
    sys.exit(1 if fails else 0)
