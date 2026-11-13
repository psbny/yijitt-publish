# -*- coding: utf-8 -*-
"""文件简介：本地模型网关链（m07729：旧模型通道停用，全部换成本机网关）。

`config.yaml` 的 `llm.providers` 是有序列表，每项：
    name      显示名（日志用）
    base      网关地址，默认 `http://127.0.0.1:3425/v1`（本机模型网关）
    model     模型 id，例如 `local/model-a`
    key_env   读 key 的环境变量名，默认 `LLM_GATEWAY_KEY`
    key_file  可选，key 文件路径；留空时读 `~/.config/llm-gateway/.env`

按顺序试：HTTP 非 200 / 返回空正文 / 超时 / 结构异常 → 记一行日志换下一个；
全失败抛 `LLMError`，由调用方（章节筛选、星座正名、标题排序）各自降级。
所有网关都是本机地址，一律不走代理（`proxies=None`）。
"""
import json
import os

import requests

DEFAULT_BASE = "http://127.0.0.1:3425/v1"
DEFAULT_KEY_ENV = "LLM_GATEWAY_KEY"


class LLMError(RuntimeError):
    """所有网关都不可用时抛出。"""


def read_env_value(name, path=None):
    r"""从本机配置文件里读一个变量（定时任务里没有 shell 环境变量，读文件更可靠）。"""
    candidates = []
    if path:
        candidates.append(os.path.expandvars(path))
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, ".config", "llm-gateway", ".env"))
    for p in candidates:
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == name:
                        return v.strip().strip("\"'")
        except Exception:
            continue
    return ""


def providers(cfg):
    """按配置顺序返回可用网关 [{"name","base","model","key"}, ...]；缺 key 的跳过。"""
    lc = (cfg.get("llm") or {})
    items = lc.get("providers") or []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        model = (it.get("model") or "").strip()
        if not model:
            continue
        base = (it.get("base") or lc.get("base") or DEFAULT_BASE).strip()
        env = it.get("key_env") or lc.get("key_env") or DEFAULT_KEY_ENV
        key = os.environ.get(env, "") or read_env_value(env, it.get("key_file") or lc.get("key_file") or "")
        if not key:
            continue
        out.append({
            "name": (it.get("name") or model).strip(),
            "base": base,
            "model": model,
            "key": key,
        })
    return out


def chat(cfg, messages, max_tokens=None, timeout=None, log=print, tag=""):
    """依次尝试各网关，返回 (正文, 网关名)；全失败抛 LLMError。"""
    lc = (cfg.get("llm") or {})
    mt = int(max_tokens or lc.get("max_tokens") or 4000)
    to = int(timeout or lc.get("timeout") or 60)

    provs = providers(cfg)
    if not provs:
        raise LLMError("没有可用网关（检查 config.yaml 的 llm.providers 与 %s）" % DEFAULT_KEY_ENV)

    errs = []
    for p in provs:
        body = {"model": p["model"], "messages": messages, "max_tokens": mt}
        try:
            r = requests.post(
                p["base"].rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + p["key"], "Content-Type": "application/json"},
                data=json.dumps(body).encode("utf-8"),
                timeout=to,
                proxies=None,
            )
            if r.status_code != 200:
                raise RuntimeError("HTTP %d：%s" % (r.status_code, (r.text or "")[:120].replace("\n", " ")))
            j = r.json()
            if "choices" not in j:
                raise RuntimeError("接口返回异常：%s" % json.dumps(j, ensure_ascii=False)[:120])
            txt = ((j["choices"][0].get("message") or {}).get("content") or "").strip()
            if not txt:
                raise RuntimeError("模型返回空正文")
            if tag:
                log("    [LLM %s] 用 %s 成功" % (tag, p["name"]))
            return txt, p["name"]
        except Exception as e:  # noqa: BLE001
            errs.append("%s：%s" % (p["name"], str(e)[:80]))
            log("    [LLM 换下一个] %s 失败：%s" % (p["name"], str(e)[:80]))

    raise LLMError("全部网关都失败：" + "；".join(errs))
