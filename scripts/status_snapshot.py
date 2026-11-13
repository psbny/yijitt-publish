# -*- coding: utf-8 -*-
r"""文件简介：只读状态快照。一条命令看清"现在处于什么状态"，不联网、不花钱、不写任何文件。

用法（项目根目录）：
    .\.venv\Scripts\python.exe scripts\status_snapshot.py
"""
import argparse
import collections
import datetime as _dt
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK = "内容自动发布每日更新"


def _line(*parts):
    print(" ".join(str(p) for p in parts))


def _read_json(path, default=None):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        _line("  [读不到] %s：%s" % (os.path.basename(path), exc))
        return default


def _decode(raw):
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def section_state():
    _line("==", "状态文件")
    for name in ("PAUSE", "ALERT.md"):
        p = os.path.join(ROOT, name)
        _line("  %-9s %s" % (name, "存在" if os.path.exists(p) else "不存在"))
    d = _read_json(os.path.join(ROOT, "state.json"), {}) or {}
    vids = d.get("videos") or {}
    c = collections.Counter((v or {}).get("status", "-") for v in vids.values())
    _line("  videos    %d 条 %s" % (len(vids), dict(c)))
    waiting = d.get("waiting") or {}
    wc = collections.Counter((v or {}).get("status", "-") for v in waiting.values())
    _line("  waiting   %d 条 %s" % (len(waiting), dict(wc)))
    firsts = {}
    for rec in waiting.values():
        rec = rec or {}
        st = rec.get("status") or "-"
        f = rec.get("first_at") or rec.get("at") or ""
        if f and (st not in firsts or f < firsts[st]):
            firsts[st] = f
    for st in sorted(firsts):
        _line("    最早一条 %-12s %s（今晚会回补）" % (st, firsts[st]))
    _line("  pending   %d 条" % len(d.get("pending") or []))
    _line("  runs      记录 %d 次；updated_at=%s" % (len(d.get("runs") or []), d.get("updated_at")))


def _pick_runs(logs, limit=2):
    runs = [f for f in os.listdir(logs) if f.startswith("run-") and f.endswith(".json")]
    runs.sort(key=lambda f: os.path.getmtime(os.path.join(logs, f)), reverse=True)
    picked, seen_real = [], False
    for f in runs:
        d = _read_json(os.path.join(logs, f), {}) or {}
        real = (d.get("mode") != "dry-run") and (d.get("total") or 0) >= 10
        if real and not seen_real:
            picked.append((f, d, True))
            seen_real = True
        elif not real and len(picked) < 2:
            picked.append((f, d, False))
        if len(picked) >= 2:
            break
    return picked


def section_last_run():
    _line("==", "最近一次运行")
    logs = os.path.join(ROOT, "logs")
    if not os.path.isdir(logs):
        _line("  没有 logs 目录")
        return
    for f, d, real in _pick_runs(logs):
        mt = _dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(logs, f)))
        tag = "实跑" if real else "非实跑（dry-run/空跑）"
        _line("  [%s] %s（%s）" % (tag, f, mt.strftime("%Y-%m-%d %H:%M")))
        _line("   模式 %s / %s 条 / 用时 %s 分" % (d.get("mode"), d.get("total"),
                                            round((d.get("elapsed_sec") or 0) / 60, 1)))
        c = collections.Counter((r or {}).get("status", "-") for r in (d.get("results") or []))
        _line("   结果分布 %s" % dict(c))
    rep = os.path.join(logs, "report-latest.txt")
    if os.path.exists(rep):
        with io.open(rep, encoding="utf-8") as f:
            for x in [x.rstrip() for x in f.readlines()]:
                if x.startswith("结论") or "余额" in x:
                    _line("  日报 %s" % x)


def section_task():
    _line("==", "任务计划")
    try:
        out = subprocess.run(["schtasks", "/Query", "/TN", TASK, "/FO", "LIST", "/V"],
                             capture_output=True, timeout=20).stdout
    except Exception as exc:  # noqa: BLE001
        _line("  查询失败：%s" % exc)
        return
    text = _decode(out)
    want = ("状态", "Status", "上次运行时间", "Last Run Time", "上次结果", "Last Result",
            "下次运行时间", "Next Run Time", "上次结果", "LastTaskResult")
    for raw in text.splitlines():
        s = raw.strip()
        if any(s.startswith(k) for k in want):
            _line("  " + " ".join(s.split()))


def section_git():
    _line("==", "代码版本")
    try:
        head = _decode(subprocess.run(["git", "log", "--oneline", "-1"], cwd=ROOT,
                                      capture_output=True, timeout=15).stdout).strip()
        dirty = _decode(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                       capture_output=True, timeout=15).stdout).strip()
        _line("  HEAD      %s" % (head or "（无提交）"))
        _line("  未提交    %d 个文件" % (len([x for x in dirty.splitlines() if x.strip()])))
    except Exception as exc:  # noqa: BLE001
        _line("  git 不可用：%s" % exc)


def section_config():
    _line("==", "配置摘要（不显示密钥）")
    try:
        import yaml  # noqa: PLC0415
        with io.open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        _line("  读配置失败：%s" % exc)
        return
    llm = cfg.get("llm") or {}
    names = [p.get("name") for p in (llm.get("providers") or [])]
    _line("  网关链    %s" % (names or "（未配置）"))
    _line("  chapterai %s" % ("开" if (cfg.get("chapterai") or {}).get("enabled") else "关"))
    _line("  标题翻译  %s" % ("谷歌直译" if (cfg.get("translate") or {}).get("use_google") else "不翻，交平台"))
    docx_path = cfg.get("blogger_docx") or ""
    if docx_path and os.path.exists(docx_path):
        try:
            from docx import Document  # noqa: PLC0415
            paras = [x.text.strip() for x in Document(docx_path).paragraphs if x.text.strip()]
            _line("  博主名单  %d 位（%s）" % (len([x for x in paras if x.startswith("【")]), os.path.basename(docx_path)))
        except Exception as exc:  # noqa: BLE001
            _line("  博主名单  读不到：%s" % exc)
    else:
        _line("  博主名单  路径不存在：%s" % (docx_path or "（未配置）"))
    targets = (cfg.get("report") or {}).get("targets") or []
    _line("  日报推送  %d 个目标" % len(targets))
    ck = os.path.join(ROOT, "data", "yt-cookies.txt")
    if os.path.exists(ck):
        mt = _dt.datetime.fromtimestamp(os.path.getmtime(ck))
        _line("  cookie    %s 导出（%d 字节）" % (mt.strftime("%Y-%m-%d"), os.path.getsize(ck)))
    else:
        _line("  cookie    不存在（YouTube 会要求登录）")


def section_balance():
    _line("==", "余额（联网只读，不花钱）")
    try:
        import sys as _sys  # noqa: PLC0415
        _sys.path.insert(0, os.path.join(ROOT, "src"))
        import yaml  # noqa: PLC0415
        from tarot_pipeline.backend import Client  # noqa: PLC0415
        with io.open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        c = Client(os.path.join(ROOT, cfg.get("cookie_file") or "cookies.json"), log=lambda *a: None)
        u = c.user_info()
        bal = u.get("balance")
        _line("  余额      %s 币（%s，updated %s）" % (bal, u.get("nickname"), u.get("modified_on")))
        if isinstance(bal, (int, float)):
            _line("  还能跑   约 %d 轮（按 416 币/轮）" % int(bal // 416))
    except Exception as exc:  # noqa: BLE001
        _line("  查询失败：%s" % exc)


def main():
    ap = argparse.ArgumentParser(description="只读状态快照")
    ap.add_argument("--online", action="store_true", help="额外查一次真实余额（联网只读）")
    args = ap.parse_args()
    _line("yijitt-publish · 状态快照 · %s" % _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    _line("")
    section_state()
    _line("")
    section_last_run()
    _line("")
    section_task()
    _line("")
    section_git()
    _line("")
    section_config()
    if args.online:
        _line("")
        section_balance()
    _line("")
    _line("提示：本脚本只读。要真跑一轮花 350–470 币，先看 RULES.md 的红线一节。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
