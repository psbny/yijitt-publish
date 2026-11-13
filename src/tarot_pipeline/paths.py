# -*- coding: utf-8 -*-
"""文件简介：项目里所有"东西放哪儿"的唯一出处。

改造前各模块各自用 `__file__` 往上数两级找项目根，搬进 src/ 之后那套算法就错了，
所以统一收到这里。三种东西分开：
  - 代码（这个包自己）      PKG_DIR
  - 运行时数据/日志/工作区  DATA_DIR / LOG_DIR / WORK_DIR / SRT_DIR
  - 配置与规则              CONFIG_PATH / RULES_PATH

项目根默认是包目录上上级（`<root>/src/tarot_pipeline` -> `<root>`）；如果用
`pip install` 装到别处、数据放在另一个盘，就设环境变量 TAROT_HOME 指过去。
"""
from __future__ import annotations

import os

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(PKG_DIR)

#: 项目根：优先环境变量 TAROT_HOME，其次按源码树位置推断
PROJECT_ROOT = os.environ.get("TAROT_HOME") or os.path.dirname(SRC_DIR)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
WORK_DIR = os.path.join(PROJECT_ROOT, "work")
SRT_DIR = os.path.join(WORK_DIR, "srt")

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
RULES_PATH = os.path.join(PROJECT_ROOT, "rules.yaml")

#: 备份、截图、日志里常被引用的几处
DEFAULT_COOKIES = os.path.join(DATA_DIR, "yt-cookies.txt")
RANK_CACHE = os.path.join(DATA_DIR, "rank-cache.json")


def ensure_dirs():
    """开跑前把该有的目录建好（只建目录，不碰文件）。"""
    for d in (DATA_DIR, LOG_DIR, WORK_DIR, SRT_DIR):
        os.makedirs(d, exist_ok=True)
    return [DATA_DIR, LOG_DIR, WORK_DIR, SRT_DIR]
