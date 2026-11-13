# -*- coding: utf-8 -*-
"""文件简介：用模型处理章节（m04376 筛章节 + m06052 星座正名）。

两件事：
1. `screen()`   ——哪些时间戳该留、哪些是开场/广告/闲聊该丢（规则筛不干净）。
2. `normalize_signs()` ——全星座视频的章节名写法太乱（SAG / CAP / AQUA / 西语 / emoji），
   交给模型认成 12 个标准中文星座名。**只改名字，时间戳一律用我们自己解析的**，
   模型失败/乱码/超时就返回 None，调用方保持原来的 hold 行为。

调用通道（m07729：旧模型通道停用，改为 `llm.py` 的本地网关链）：
   `config.yaml` 的 `llm.providers` 按顺序试，一个网关失败就换下一个，全失败则降级。
"""
import json
import re

from . import core
from . import llm

SYSTEM = """你在整理塔罗视频的时间戳目录，输出给中文观众看。只输出序号，不要解释。"""

PROMPT_PICK = """这是一个"选组"塔罗视频的章节列表：

{lines}

任务：挑出**真正给观众选的选项**（对应桌上摆的几组牌/物件，一般 2~3 个，最多 3 个）。
必须丢掉：开场白、打招呼、频道介绍、订阅/点赞提醒、抽牌说明、广告、结尾、时间戳说明、首页（Home/INICIO/Introdução）。
注意：
- 有的视频没有"首页"这一条，直接从第一个选项开始，这种情况把选项全留下。
- 选项名可能是外语（Opción 1 / Opção 2 / Pile 1 / 选项一）或只有物件名（羽毛、月光石）。
- 保持原有先后顺序，不要重排。
只输出要保留的序号，用英文逗号分隔，例如：1,3,4"""

PROMPT_ALL = """这是一个"全星座"塔罗视频的章节列表：

{lines}

任务：只保留 12 个星座那几行（白羊座…双鱼座，可能是英文/西语/葡语/韩语写法），
丢掉开场、广告、订阅提醒、总结、以及除星座之外的其它分段。保持原有顺序。
只输出要保留的序号，用英文逗号分隔，例如：2,3,4,5,6,7,8,9,10,11,12,13"""


def _parse_idx(text, n):
    out, seen = [], set()
    buf = ""
    for ch in (text or "") + " ":
        if ch.isdigit():
            buf += ch
        else:
            if buf:
                v = int(buf)
                if 1 <= v <= n and v not in seen:
                    out.append(v - 1)
                    seen.add(v)
                buf = ""
    return out


def screen(cfg, cn, title, vtype, chapters, log=print):
    """返回筛过的章节列表；任何异常都返回 None，让调用方用规则结果。"""
    if not chapters or len(chapters) < 2 or vtype == core.TYPE_ENERGY:
        return None
    lines = "\n".join("%d. %s —— %s" % (i + 1, c.name, c.hhmmss()) for i, c in enumerate(chapters))
    tpl = PROMPT_PICK if vtype == core.TYPE_PICK else PROMPT_ALL
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": tpl.format(lines=lines)}]
    try:
        raw, _gw = llm.chat(cfg, msgs, max_tokens=1000, timeout=90, log=log, tag="章节筛选")
    except Exception as e:
        log("    [章节筛选降级] %s" % str(e)[:90])
        return None
    idx = _parse_idx(raw, len(chapters))
    if not idx:
        log("    [章节筛选降级] 模型没给出序号：%r" % (raw or "")[:60])
        return None
    kept = [chapters[i] for i in idx]
    if vtype == core.TYPE_PICK:
        kept = kept[:3]
    log("    章节筛选：%d 条 -> %d 条（%s）" % (len(chapters), len(kept), ", ".join(c.name for c in kept)[:60]))
    return kept


# --------------------------------------------------------------------------
# 星座正名（m06052）：章节名 -> 12 个标准中文星座名
# --------------------------------------------------------------------------

SIGNS = list(core.ZODIAC_CN)

PROMPT_NORMALIZE = (
    "这是一个「全星座」塔罗视频的章节名列表，写法很乱（英文、西语、葡语、韩语、缩写、emoji 混着来）。\n"
    "请判断每一条对应哪个星座。\n"
    "只能从这 12 个中文名里选：{signs}。\n"
    "不是星座的条目（开场、广告、订阅提醒、总结等）回答 \"-\"。\n"
    "只输出一个 JSON 对象：键是序号（字符串），值是星座名或 \"-\"；不要解释，不要代码块。\n"
    "示例：{{\"1\":\"白羊座\",\"2\":\"-\"}}\n\n章节列表：\n{lines}"
)


def _parse_mapping(raw, n):
    """从模型输出里抠出 {序号-1: 星座名}；只收 12 个标准名，其它一律忽略。"""
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        try:
            i = int(str(k).strip()) - 1
        except Exception:
            continue
        if not (0 <= i < n):
            continue
        val = str(v).strip()
        if val in SIGNS:
            out[i] = val
    return out


def normalize_signs(cfg, chapters, log=print, min_signs=12):
    """把章节名认成 12 星座。成功返回 {序号: 中文名}，认不全/失败返回 None。

    只改名字：秒数（时间戳）永远用 core.parse_chapters 解析出来的那份。

    min_signs：要认出多少个不同星座才采纳。判定前兜底用 10（够判全星座即可），
    判定后修正（要求 12 个齐才发）用默认 12。
    """
    if not chapters or len(chapters) < 8:
        return None
    if len(core.zodiac_hits_names(chapters)) >= min_signs:
        return None                      # 已经够用，不用花钱

    cc = (cfg.get("chapterai") or {})
    if not cc.get("enabled", True):
        return None

    lines = "\n".join("%d. %s" % (i + 1, (c.name or "").strip()) for i, c in enumerate(chapters))
    msgs = [
        {"role": "system", "content": "你在做星座章节名标准化，只输出 JSON，不要任何解释。"},
        {"role": "user", "content": PROMPT_NORMALIZE.format(signs="、".join(SIGNS), lines=lines)},
    ]
    timeout = int(cc.get("timeout") or 20)

    try:
        raw, gw = llm.chat(cfg, msgs, max_tokens=800, timeout=timeout, log=log, tag="星座正名")
    except Exception as e:
        log("    [星座正名降级] %s" % str(e)[:100])
        return None

    mapping = _parse_mapping(raw, len(chapters))
    got = len(set(mapping.values()))
    if got >= min_signs:
        log("    星座正名（%s）：%d 条章节认出 %d 星座" % (gw, len(mapping), got))
        return mapping
    log("    [星座正名降级] %s 没认出 %d 星座（只认出 %d 个）：%r"
        % (gw, min_signs, got, (raw or "")[:80]))
    return None
