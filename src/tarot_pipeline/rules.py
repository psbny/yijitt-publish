# -*- coding: utf-8 -*-
"""文件简介：读 rules.yaml 里的可调参数（价格/时段/上限/窗口/条数），全项目唯一的数字来源。

为什么要单独一层：以前价格写在 lib/schedule.py、时长上限写在 lib/core.py、条数写在
config.yaml，改一个价钱得改 Python 源码。现在代码只读这里，rules.yaml 改完立刻生效。
"""
import io
from . import paths

import os

import yaml

HERE = paths.PROJECT_ROOT
PATH = os.path.join(HERE, "rules.yaml")

# 读不到文件或字段缺失时的兜底，保证程序不会因为少一个键就崩
DEFAULTS = {
    "price": {"energy": 29, "pick": 59, "all_signs": 79},
    "schedule": {
        "ep_hours": list(range(8, 24)),
        "as_hours": [9, 14, 21, 16, 19],
        "ep_start_minute": 5,
        "as_start_minute": 15,
        "minute_step": 5,
    },
    "duration_limit_minutes": {"energy": 30, "all_signs": 240},
    "window_hour": 21,
    "max_videos_per_channel": 3,
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    """读 rules.yaml，缺字段用 DEFAULTS 补齐。"""
    p = path or PATH
    try:
        with io.open(p, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}
    except Exception:
        data = {}
    return _merge(DEFAULTS, data)


DATA = load()


def price(vtype):
    """按类型取价格（单位：分）。"""
    return int(DATA["price"].get(vtype, 0))


def duration_limit_seconds(vtype):
    """按时长上限取秒数；没有上限的类型返回 0。"""
    mins = DATA["duration_limit_minutes"].get(vtype)
    return int(mins) * 60 if mins else 0
