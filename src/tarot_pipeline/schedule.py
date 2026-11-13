"""文件简介：发布时段排期引擎。

规则来自用户 m01172 的口述，逐条对应：

1. 前一天更新后一天的：11/4 更新 -> 11/5 发布。
2. 能量 / 选组：从 8:05 到 23:05 每小时一个槽位，排满后整轮 +5 分钟
   （8:10~23:10、8:15~23:15 …），按顺序依次占位。
3. 全星座：数量少，广撒网，分散在流量好的时段，分钟比当日能量轮次
   再往后 5 分钟。优先 9:15 / 14:15 / 21:15，其次 16:15 / 19:15，
   溢出再往下 9:20 / 14:20 …
4. 必须避开当天已经被占用的槽位（后台里已有的定时发布文章）。

时间一律按 Asia/Shanghai 解释（后台 scheduled_at 就是这个时区的 unix）。
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from . import rules as _rules

TZ = ZoneInfo("Asia/Shanghai")

# 数字全部来自 rules.yaml（唯一来源，见 lib/rules.py）：改时段/价格只改那个文件
_R = _rules.DATA
EP_HOURS = tuple(_R["schedule"]["ep_hours"])        # 能量 / 选组：8 点到 23 点
AS_HOURS = tuple(_R["schedule"]["as_hours"])        # 全星座优先时段（顺序即优先级）
EP_START_MINUTE = int(_R["schedule"]["ep_start_minute"])
AS_START_MINUTE = int(_R["schedule"]["as_start_minute"])
MINUTE_STEP = int(_R["schedule"]["minute_step"])
MAX_MINUTE = 59

# 类型常量与 lib.core 保持一致（core.TYPE_ENERGY / core.TYPE_PICK / core.TYPE_ALL_SIGNS）
TYPE_ENERGY = "energy"
TYPE_PICK = "pick"
TYPE_ALL_SIGNS = "all_signs"

# 价格单位是「分」：0.29 元 = 29
PRICE = {t: _rules.price(t) for t in (TYPE_ENERGY, TYPE_PICK, TYPE_ALL_SIGNS)}


def _slots(hours, start_minute, need):
    """按「轮次递增 5 分钟」的方式生成时段。"""
    out = []
    r = 0
    while len(out) < need:
        minute = start_minute + MINUTE_STEP * r
        if minute > MAX_MINUTE:
            break
        for h in hours:
            if len(out) >= need:
                break
            out.append((h, minute))
        r += 1
    return out


def ep_slots(need):
    return _slots(EP_HOURS, EP_START_MINUTE, need)


def as_slots(need):
    return _slots(AS_HOURS, AS_START_MINUTE, need)


def publish_date_for(run_date, days_ahead=1):
    return run_date + dt.timedelta(days=days_ahead)


def occupied_slots(posts, date):
    """从后台文章列表里取出指定日期已被占用的 (hour, minute)。"""
    out = set()
    for p in posts or []:
        pub = (p.get("published_on") or "").strip()
        if not pub:
            continue
        try:
            when = dt.datetime.strptime(pub, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                when = dt.datetime.strptime(pub[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
        if when.date() == date:
            out.add((when.hour, when.minute))
    return out


def plan(items, publish_date, occupied=()):
    """把 items 分配到 publish_date 的时段。

    items: [{"cn": 中文名, "vtype": 能量/选组/全星座, ...}]，原地不改
    返回：同样的 dict 加上 at(datetime) / ts(unix int) / price(分)，
          按发布时间升序
    """
    occupied = set(occupied or ())
    ep = [x for x in items if x.get("vtype") in (TYPE_ENERGY, TYPE_PICK)]
    au = [x for x in items if x.get("vtype") == TYPE_ALL_SIGNS]

    pool_ep = [s for s in ep_slots(len(ep) + len(occupied) + 64) if s not in occupied]
    # 全星座还要避开本批次能量/选组刚占掉的槽位，避免同一分钟两条
    taken = occupied | set(pool_ep[:len(ep)])
    pool_au = [s for s in as_slots(len(au) + len(taken) + 64) if s not in taken]
    if len(pool_ep) < len(ep):
        raise ValueError("当天能量/选组时段不够分配（需要 %d 个）" % len(ep))
    if len(pool_au) < len(au):
        raise ValueError("当天全星座时段不够分配（需要 %d 个）" % len(au))

    out = []
    for x, (h, m) in zip(ep, pool_ep):
        out.append(_stamp(x, publish_date, h, m))
    for x, (h, m) in zip(au, pool_au):
        out.append(_stamp(x, publish_date, h, m))
    return sorted(out, key=lambda x: x["at"])


def _stamp(item, date, hour, minute):
    at = dt.datetime(date.year, date.month, date.day, hour, minute, tzinfo=TZ)
    return {
        **item,
        "at": at,
        "ts": int(at.timestamp()),
        "price": PRICE.get(item.get("vtype"), 79),
        "hhmm": "%02d:%02d" % (hour, minute),
    }


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    demo = [{"cn": "Aura", "vtype": TYPE_ALL_SIGNS}, {"cn": "Harmoni", "vtype": TYPE_ALL_SIGNS},
            {"cn": "Lina", "vtype": TYPE_ALL_SIGNS}, {"cn": "Deepa", "vtype": TYPE_PICK},
            {"cn": "Wisdom", "vtype": TYPE_ENERGY}]
    d = publish_date_for(dt.date(2026, 11, 4))
    occ = {(16, 15), (21, 15), (14, 15), (15, 10), (9, 15)}
    for row in plan(demo, d, occ):
        print(row["hhmm"], row["vtype"], row["cn"], row["price"], row["ts"])
