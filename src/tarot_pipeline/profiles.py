"""文件简介：博主画像记忆库。

目的（用户 m01172 第 4 条）：每个博主更新的类型基本固定，记住之后下次不用
每个博主都打开视频/直播去猜，也记住「单星座批量」「直播回放为主」这类特点。

文件：data/profiles.json
  {
    "Aura": {
      "types": {"全星座": 12},
      "durations": [10770, 9800],
      "live": 11, "video": 1,
      "skip": false,
      "notes": []
    }
  }
"""
from __future__ import annotations

import io
from . import paths

import json
import os

HERE = paths.PROJECT_ROOT
PATH = os.path.join(HERE, "data", "profiles.json")


def load() -> dict:
    if os.path.exists(PATH):
        try:
            with io.open(PATH, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, PATH)


def record(cn: str, vtype: str, duration: int = 0, was_live: bool = False) -> dict:
    """记一次更新。返回该博主的最新画像。"""
    data = load()
    p = data.setdefault(cn, {"types": {}, "durations": [], "live": 0, "video": 0,
                             "skip": False, "notes": []})
    p["types"][vtype] = int(p["types"].get(vtype, 0)) + 1
    if duration:
        p["durations"] = (p.get("durations") or [])[-9:] + [int(duration)]
    if was_live:
        p["live"] = int(p.get("live", 0)) + 1
    else:
        p["video"] = int(p.get("video", 0)) + 1
    save(data)
    return p


def dominant(cn: str):
    """返回该博主历史最多的类型（样本 >= 3 才算），否则 None。"""
    p = load().get(cn) or {}
    types = p.get("types") or {}
    if not types or sum(types.values()) < 3:
        return None
    return max(types.items(), key=lambda kv: kv[1])[0]


def is_energy_only(cn: str) -> bool:
    """历史几乎全是能量类 -> 不用去评论区找时间戳。"""
    p = load().get(cn) or {}
    types = p.get("types") or {}
    if sum(types.values()) < 3:
        return False
    return types.get("能量", 0) >= 0.8 * sum(types.values())


def is_live_heavy(cn: str) -> bool:
    p = load().get(cn) or {}
    live, video = int(p.get("live", 0)), int(p.get("video", 0))
    return live > 0 and live >= video


def add_note(cn: str, note: str) -> None:
    """只记特点，不把这个博主标成跳过。"""
    data = load()
    p = data.setdefault(cn, {"types": {}, "durations": [], "live": 0, "video": 0,
                             "skip": False, "notes": []})
    notes = p.get("notes") or []
    if note not in notes:
        p["notes"] = notes + [note]
        save(data)


def mark_skip(cn: str, note: str = "") -> None:
    data = load()
    p = data.setdefault(cn, {"types": {}, "durations": [], "live": 0, "video": 0,
                             "skip": False, "notes": []})
    p["skip"] = True
    if note and note not in (p.get("notes") or []):
        p["notes"] = (p.get("notes") or []) + [note]
    save(data)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("profiles:", len(load()))
