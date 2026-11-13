# -*- coding: utf-8 -*-
"""文件简介：`python -m tarot_pipeline` 的入口，等价于 `tarot-pipeline`。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
