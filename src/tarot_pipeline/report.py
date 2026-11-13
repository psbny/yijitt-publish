# -*- coding: utf-8 -*-
r"""文件简介：把当天那次自动运行的日志与报告渲染成一份「日报」文本，写进 logs\report-latest.txt，
并可按 config.yaml 的 report.targets 推送到IM（IM 群机器人 / 通用 webhook / 通用 webhook）。

用法：
    python report.py                 # 渲染最近一次「真正提交过」的运行，写 logs\report-<时间>.txt 与 report-latest.txt
    python report.py --print         # 只打印，不写文件（调试用）
    python report.py --push          # 渲染并推送；run_daily.bat 跑完会调这个
    python report.py --push --file logs\report-latest.txt   # 把已有文本重发（手动补发用）

设计：不改 pipeline.py，只解析它写出的 daily.log 与 run-*.json —— 报表口径与人工汇报一致。
"""
import argparse
from . import paths

import datetime
import io
import json
import os
import re
import sys
import urllib.request

HERE = paths.PROJECT_ROOT
LOGS = os.path.join(HERE, "logs")
DAILY = os.path.join(LOGS, "daily.log")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 某些终端不支持重配，忽略即可
        pass


def say(msg):
    print("[report] %s" % msg)


def load_cfg():
    try:
        import yaml
    except ImportError:
        say("没有 PyYAML，跳过配置（只写文件不推送）")
        return {}
    try:
        with io.open(os.path.join(HERE, "config.yaml"), encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        say("读 config.yaml 失败：%s" % e)
        return {}


# ---------------------------------------------------------------- 日志分段
def segments():
    """按「开始每日更新」切段，返回 [(首行, [行...])]。"""
    if not os.path.exists(DAILY):
        return []
    with io.open(DAILY, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    starts = [i for i, l in enumerate(lines) if "开始每日更新" in l]
    out = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.append((lines[i], lines[i:end]))
    return out


def pick_segment():
    """优先最近一次真正提交过的运行（有「提交成功」），跳过 dry-run。"""
    segs = segments()
    if not segs:
        return "", []
    for head, seg in reversed(segs):
        if any("提交成功" in l for l in seg):
            return head, seg
    return segs[-1]


def _time_of(line):
    m = re.search(r"(\d{2}):(\d{2}):(\d{2})", line)
    return m.group(0) if m else ""


def _date_of(line):
    m = re.search(r"(\d{4})/(\d{2})/(\d{2})", line)
    return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3)) if m else ""


# ---------------------------------------------------------------- 解析
# 直播预告/刚结束不是"报错"，是等时间（用户 2026-11-06 要求日报与时俱进，别把它们算进报错）
LIVE_PAT = re.compile(r"live event (will begin|has ended)", re.I)


def parse(head, seg):
    d = {
        "start": _time_of(head), "day": _date_of(head), "user": "", "pause": False,
        "balance_before": None, "channels": None, "channels_total": None,
        "scan_secs": None, "candidates": None,
        "processed": None, "retry": set(), "submit_ok": None, "submit_total": None, "dup": 0,
        "done_ok": None, "done_bad": None, "elapsed_min": None,
        "publish": [], "publish_fail": [], "errors": [], "live": [],
    }
    for l in seg:
        if "检测到 PAUSE 文件" in l:
            d["pause"] = True
        m = re.search(r"登录用户：(.+?)，余额 (\d+) 币", l)
        if m:
            d["user"], d["balance_before"] = m.group(1), int(m.group(2))
        m = re.search(r"阶段1 完成：共扫描 (\d+) 个频道，(\d+) 个有窗口内新视频，([\d.]+)s，(\d+) 条候选", l)
        if m:
            d["channels_total"], d["channels"], d["scan_secs"], d["candidates"] = (
                int(m.group(1)), int(m.group(2)), float(m.group(3)), int(m.group(4)))
        else:
            # 2026-11-12 之前的日志没有「共扫描」口径，退回旧格式
            m = re.search(r"阶段1 完成：(\d+) 个频道扫完，([\d.]+)s，(\d+) 条候选", l)
            if m:
                d["channels"], d["scan_secs"], d["candidates"] = (
                    int(m.group(1)), float(m.group(2)), int(m.group(3)))
        m = re.search(r"阶段2/5 并发处理 (\d+) 条", l)
        if m:
            d["processed"] = int(m.group(1))
        m = re.search(r"回补·(\S{6,})", l)
        if m:
            d["retry"].add(m.group(1))
        m = re.search(r"阶段3 完成：(\d+)/(\d+) 提交成功", l)
        if m:
            d["submit_ok"], d["submit_total"] = int(m.group(1)), int(m.group(2))
        # 2026-11-07 修：这 2 条不是提交失败，是平台已经有同 hash 的文件、主动去重跳过，
        # 之前被算进「提交失败 2 条」误报给用户。
        if "重复跳过" in l:
            d["dup"] += 1
        m = re.search(r"全部完成：(\d+) 条就绪/已提交，(\d+) 条跳过/失败，总用时 ([\d.]+) 分", l)
        if m:
            d["done_ok"], d["done_bad"], d["elapsed_min"] = int(m.group(1)), int(m.group(2)), float(m.group(3))
        m = re.search(r"已排期 (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) ¥([\d.]+) 封面=(\S+) 正文 (\d+) 字 频道=(\S+)", l)
        if m:
            chan = m.group(6)
            d["publish"].append({
                "date": m.group(1), "time": m.group(2), "price": float(m.group(3)),
                "cover": m.group(4), "chars": int(m.group(5)),
                "channel": "未匹配" if chan.lower() in ("none", "null", "-") else chan,
            })
        if "排期失败" in l:
            d["publish_fail"].append(l.split("排期失败：", 1)[-1][:110])
        if re.search(r"ERROR:|Traceback|提交失败|处理失败", l) and len(d["errors"]) < 8:
            short = l.split("] ", 1)[-1][:120]
            if LIVE_PAT.search(l):
                d["live"].append(short)
            else:
                d["errors"].append(short)
    return d


def run_json(d):
    """按「开始时间 + 时长」挑出对应的 run-*.json（JSON 在运行结束时才写）。"""
    if not os.path.isdir(LOGS):
        return None, {}
    best, best_gap, payload = None, None, {}
    for f in sorted(x for x in os.listdir(LOGS) if x.startswith("run-") and x.endswith(".json")):
        try:
            with io.open(os.path.join(LOGS, f), encoding="utf-8") as fh:
                p = json.load(fh)
        except Exception:
            continue
        if d.get("day") and not str(p.get("at", "")).startswith(d["day"]):
            continue
        try:
            at = datetime.datetime.strptime(p["at"], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            continue
        if d.get("start"):
            hh, mm, ss = (int(x) for x in d["start"].split(":"))
            base = at.replace(hour=hh, minute=mm, second=ss)
            gap = abs((at - base).total_seconds() - (d.get("elapsed_min") or 0) * 60)
        else:
            gap = 0
        if best_gap is None or gap < best_gap:
            best, best_gap, payload = f, gap, p
    return best, payload


def tally(payload):
    """stat / 花费 / 总数 / 直播等待条数（直播预告、刚结束的直播从 error 里摘出来）。"""
    stat, cost, total, live = {}, 0, 0, 0
    for r in payload.get("results", []):
        st = r.get("status") or "?"
        if st == "error" and LIVE_PAT.search(str(r.get("reason") or "")):
            st = "live_wait"
            live += 1
        stat[st] = stat.get(st, 0) + 1
        cost += int(r.get("cost") or 0)
        total += 1
    return stat, cost, total, live


# ---------------------------------------------------------------- 渲染
def render(d, stat, cost, total, detail_lines=5, live=0, balance_warn=600, run_cost_hint=450):
    d.setdefault("channels_total", None)  # 旧调用方（测试）传的 dict 没有这个键
    day = d.get("day") or datetime.date.today().strftime("%Y-%m-%d")
    today = datetime.date.today().strftime("%Y-%m-%d")
    if d["pause"]:
        # 2026-11-07 修：以前只写"今天按你的设置暂停了"，但脚本崩掉/没跑成时也会落到这里，
        # 于是给用户推了一条假的"暂停了"。现在只有今天这一段确实是 PAUSE 才这么说。
        if day == today:
            return "内容发布日报 · %s\n\n今天按你的设置暂停了，21:00 没有跑。\n" % day
        return ("内容发布日报 · %s\n\n今天（%s）没有跑成：最近一段日志是 %s 的跳过记录，"
                "不是真的暂停。请检查任务计划与 logs\\daily.log。\n" % (today, today, day))

    pub = d["publish"]
    n_pub = len(pub)
    by_price = {}
    for p in pub:
        by_price[p["price"]] = by_price.get(p["price"], 0) + 1
    label = {0.29: "能量", 0.59: "选组", 0.79: "全星座", 0.89: "加急"}
    bal = d["balance_before"]
    bal_after = (bal - cost) if (bal is not None and cost) else None

    head = []
    if d["channels"] and d["channels_total"] and d["channels_total"] > d["channels"]:
        head.append("扫描 %d 个频道（%d 个有新视频）" % (d["channels_total"], d["channels"]))
    elif d["channels"]:
        head.append("%d 个频道" % d["channels"])
    if d["submit_ok"]:
        head.append("%d 条提交成功" % d["submit_ok"])
    if n_pub:
        head.append("%d 条已排期" % n_pub)
    if cost:
        head.append("花 %d 币" % cost)
    concl = "、".join(head) or "本次没有产生新内容"
    if n_pub:
        concl += "，发布日 %s" % pub[0]["date"]
    if d["elapsed_min"]:
        concl += "，用时 %.1f 分钟" % d["elapsed_min"]

    L = ["内容发布日报 · %s（%s 自动跑）" % (day, (d["start"] or "")[:5])]
    today_d = datetime.date.today()
    today = today_d.strftime("%Y-%m-%d")
    if day != today:
        # 2026-11-08 修：过了零点再手动看报表时，旧文案会说"今天没跑成"，其实是今天还没到点。
        gap = (today_d - datetime.datetime.strptime(day, "%Y-%m-%d").date()).days
        if gap == 1 and datetime.datetime.now().hour < 21:
            L.append("今天 21:00 还没到，下面是最近一次运行（%s）的报表" % day)
        elif gap == 1:
            L.append("⚠ 今天（%s）没有运行记录，最近一次是 %s，请检查任务计划/日志" % (today, day))
        else:
            L.append("⚠ 已经 %d 天没有运行记录（最近一次 %s），请检查任务计划/日志" % (gap, day))
    L += ["", "结论：" + concl + "。", "", "【数字】"]
    if d["channels"] and d["channels_total"]:
        L.append("· 扫描 %d 频道，%d 个有新视频 / %d 条候选（%.0f 秒）" % (
            d["channels_total"], d["channels"], d["candidates"] or 0, d["scan_secs"] or 0))
    elif d["channels"]:
        L.append("· 扫描 %d 频道 / %d 条候选（%.0f 秒）" % (d["channels"], d["candidates"] or 0, d["scan_secs"] or 0))
    if total:
        L.append("· 处理 %d 条：提交成功 %d / 跳过 %d / 没字幕 %d / 报错 %d" % (
            total, d["submit_ok"] if d["submit_ok"] is not None else stat.get("submitted", 0),
            stat.get("skip", 0) + stat.get("skipped", 0), stat.get("no_subs", 0), stat.get("error", 0)))
    if d["retry"]:
        L.append("· 回补旧视频 %d 条（上次没字幕/直播没开播的）" % len(d["retry"]))
    if d["dup"]:
        L.append("· 其中 %d 条以前提交过（平台已有同文件），自动去重跳过" % d["dup"])
    live_n = live or len(d["live"])
    if live_n:
        L.append("· 直播 %d 条不算失败：预告没开播 / 刚结束还没出回放，按规则留着回头补" % live_n)
    low_balance = bal_after is not None and balance_warn and bal_after < balance_warn
    if cost:
        tail = ("，余额 %d → %d" % (bal, bal_after)) if bal_after is not None else ""
        if low_balance:
            tail += " ⚠ 偏低"
        L.append("· 花费 %d 币%s" % (cost, tail))
    if low_balance:
        L.append("· ⚠ 余额只剩 %d 币，下一轮约需 %d–%d 币，请提前充值"
                 % (bal_after, int(run_cost_hint * 0.9), int(run_cost_hint * 1.1)))
    if n_pub:
        parts = ["%s %d 条（¥%.2f）" % (label.get(k, "其它"), v, k) for k, v in sorted(by_price.items())]
        L.append("· 排期 %d 条 = %s" % (n_pub, " + ".join(parts)))
        no_cover = [p for p in pub if p["cover"] != "有"]
        if no_cover:
            L.append("· 其中 %d 条没有封面" % len(no_cover))
        no_chan = [p for p in pub if p["channel"] == "未匹配"]
        if no_chan:
            L.append("· 其中 %d 条没挂频道合集（后台没建这个博主，按设定不处理）" % len(no_chan))
    if d["elapsed_min"]:
        L.append("· 总用时 %.1f 分钟" % d["elapsed_min"])

    todo = []
    if low_balance:
        todo.append("余额偏低：%d 币，下一轮约需 %d–%d 币，请提前充值"
                    % (bal_after, int(run_cost_hint * 0.9), int(run_cost_hint * 1.1)))
    if d["publish_fail"]:
        todo.append("排期失败 %d 条：%s" % (len(d["publish_fail"]), d["publish_fail"][0]))
    # 用户 2026-11-06 决定：频道不处理（后台没建对应频道时，文章照发、不挂合集）
    no_chan = [p for p in pub if p["channel"] == "未匹配"]
    if d["submit_total"] and d["submit_ok"] is not None:
        failed = d["submit_total"] - d["submit_ok"] - (d["dup"] or 0)
        if failed > 0:
            todo.append("提交失败 %d 条（%d/%d 成功，另有 %d 条去重跳过）" % (
                failed, d["submit_ok"], d["submit_total"], d["dup"] or 0))
    if d["errors"]:
        todo.append("日志报错 %d 处，最近一条：%s" % (len(d["errors"]), d["errors"][-1]))
    if todo:
        L += ["", "【要你处理】"] + ["%d. %s" % (i + 1, t) for i, t in enumerate(todo)]

    if n_pub:
        L += ["", "【排期明细】"]
        show = pub if n_pub <= detail_lines * 2 else pub[:detail_lines] + [None] + pub[-detail_lines:]
        for p in show:
            if p is None:
                L.append("… 中间 %d 条略 …" % (n_pub - detail_lines * 2))
                continue
            L.append("%s %s ¥%.2f 频道 %s" % (p["date"][5:], p["time"], p["price"], p["channel"]))
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 推送
def post_json(url, payload, timeout=12):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")[:200]


def push(text, targets):
    ok, bad = 0, []
    title = text.splitlines()[0] if text else "内容发布日报"
    for t in targets or []:
        kind = (t.get("type") or "").lower()
        try:
            if kind == "im":
                # IM 机器人：text 上限 2048 字节，markdown 上限 4096 字节，中文按 3 字节算
                body_md = text
                while len(body_md.encode("utf-8")) > 3800:
                    body_md = body_md[:-100]
                if body_md != text:
                    body_md += "\n（内容过长已截断，完整版见 logs\\report-latest.txt）"
                st, body = post_json(t["url"], {"msgtype": "markdown",
                                                "markdown": {"content": body_md}})
            elif kind == "serverchan":
                st, body = post_json("https://sctapi.ftqq.com/%s.send" % t["sendkey"],
                                     {"title": title, "desp": text})
            elif kind == "pushplus":
                st, body = post_json("https://www.pushplus.plus/send",
                                     {"token": t["token"], "title": title, "content": text, "template": "txt"})
            elif kind == "webhook":
                st, body = post_json(t["url"], dict({"text": text}, **t.get("extra", {})))
            else:
                bad.append("未知类型 %r" % t.get("type"))
                continue
            if st == 200:
                ok += 1
                say("已推送 %s：%s" % (kind, body[:80]))
            else:
                bad.append("%s：HTTP %s %s" % (kind, st, body[:60]))
        except Exception as e:
            bad.append("%s：%s" % (kind, e))
    return ok, bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="do_print", action="store_true", help="只打印，不写文件")
    ap.add_argument("--push", action="store_true", help="推送到 config.yaml 里配置的通道")
    ap.add_argument("--file", default=None, help="推送已有文本文件（不重新渲染）")
    args = ap.parse_args(argv)

    cfg = load_cfg()
    rcfg = cfg.get("report") or {}

    if args.file:
        path = args.file if os.path.isabs(args.file) else os.path.join(HERE, args.file)
        with io.open(path, encoding="utf-8") as f:
            text = f.read()
    else:
        head, seg = pick_segment()
        d = parse(head, seg)
        jf, payload = run_json(d)
        stat, cost, total, live = tally(payload)
        if cost == 0:
            cost = sum(int(r.get("cost") or 0) for r in payload.get("results", []))
        text = render(d, stat, cost, total, int(rcfg.get("detail_lines", 5)), live,
                  int(rcfg.get("balance_warn", 600)), int(rcfg.get("run_cost_hint", 450)))

    if args.do_print or not args.file:
        print(text)
    if args.do_print:
        return 0

    if not args.file:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        os.makedirs(LOGS, exist_ok=True)
        with io.open(os.path.join(LOGS, "report-%s.txt" % stamp), "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        with io.open(os.path.join(LOGS, "report-latest.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        say("已写入 logs\\report-%s.txt" % stamp)

    if args.push:
        targets = rcfg.get("targets") or []
        if not (rcfg.get("push") and targets):
            say("config.yaml 没配 report.targets，只写文件不推送")
            return 0
        ok, bad = push(text, targets)
        say("推送完成：成功 %d，失败 %d" % (ok, len(bad)))
        for b in bad:
            say("  " + b)
        return 0 if not bad else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())