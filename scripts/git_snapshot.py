# -*- coding: utf-8 -*-
"""文件简介：每天跑完给仓库记一笔（本地 git，不联网、不推送）。

为什么需要：这个项目改了十来次，以前靠手写 `xxx.bak-20261106` 留底，既占地方又对不上号。
现在每天跑完自动 commit 一次，出问题时能看出"是哪天的改动引入了问题"，也能一条命令回滚。

用法：
    python scripts\\git_snapshot.py            # 有改动就提交，没改动就跳过
    python scripts\\git_snapshot.py --dry-run  # 只看会提交什么，不真提交

注意：仓库里不含 config.yaml / state.json / cookies.json / data / logs / 封面（见 .gitignore），
所以这里的提交只涉及代码、文档、规则文件。
"""
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(args, check=False):
    p = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError("git %s 失败：%s" % (" ".join(args), (p.stderr or p.stdout).strip()[:300]))
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv

    if not os.path.isdir(os.path.join(ROOT, ".git")):
        print("[git] 不是 git 仓库，跳过（先跑一次 git init）")
        return 0

    run(["add", "-A"])
    staged = run(["diff", "--cached", "--name-only"]).stdout.strip()
    if not staged:
        print("[git] 没有改动，跳过")
        return 0

    files = [f for f in staged.splitlines() if f.strip()]
    print("[git] 待提交 %d 个文件：%s" % (len(files), ", ".join(files[:6]) + ("…" if len(files) > 6 else "")))
    if dry:
        print("[git] --dry-run，不提交")
        return 0

    msg = "每日运行 %s（%d 个文件）" % (datetime.now().strftime("%Y-%m-%d %H:%M"), len(files))
    p = run(["commit", "-m", msg])
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0:
        print("[git] 提交失败：%s" % (p.stderr or p.stdout).strip()[:300])
        return 0          # 不影响主流程
    head = run(["log", "--oneline", "-1"]).stdout.strip()
    print("[git] 已提交：%s" % head)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
