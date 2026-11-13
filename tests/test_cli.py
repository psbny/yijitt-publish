# -*- coding: utf-8 -*-
"""文件简介：CLI 分发的离线测试——不联网、不读 key、不花钱。

覆盖：版本号、帮助文本、未知子命令的退出码、portcheck 的两种结果。
`run` / `report` 需要真实环境（网络、登录态、日志），这里只验证"能分发到对的地方"，
用 --help 代替真跑。
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tarot_pipeline import cli  # noqa: E402
from tarot_pipeline.tools import portcheck  # noqa: E402

FAILED = []


def case(name):
    def deco(fn):
        try:
            fn()
            print("PASS " + name)
        except Exception as e:  # noqa: BLE001
            FAILED.append(name)
            print("FAIL %s -> %r" % (name, e))
        return fn
    return deco


@case("test_version_returns_zero")
def test_version_returns_zero():
    assert cli.main(["--version"]) == 0


@case("test_help_returns_zero")
def test_help_returns_zero():
    assert cli.main(["--help"]) == 0


@case("test_unknown_subcommand_returns_2")
def test_unknown_subcommand_returns_2():
    assert cli.main(["no-such-cmd"]) == 2


@case("test_run_help_returns_zero")
def test_run_help_returns_zero():
    # argparse 打印 help 后是 SystemExit(0)
    try:
        cli.main(["run", "--help"])
    except SystemExit as e:
        assert int(e.code or 0) == 0
        return
    raise AssertionError("run --help 没有触发 SystemExit")


@case("test_portcheck_closed_port")
def test_portcheck_closed_port():
    # 选一个几乎不可能被监听的端口
    assert portcheck.run(["59999"]) == 1


@case("test_adopt_argv_translation")
def test_adopt_argv_translation():
    assert cli._adopt_argv(["--hours", "6", "--date", "2026-11-10", "--dry-run"]) == [
        "--adopt-orphans", "6", "--date", "2026-11-10", "--dry-run"]
    assert cli._adopt_argv(["--hours=2"]) == ["--adopt-orphans", "2"]
    assert cli._adopt_argv([]) == ["--adopt-orphans", "6"]


@case("test_balance_warning")
def test_balance_warning():
    """余额低于阈值时，日报要在数字区和「要你处理」各出现一次提醒；够用时不能出现。"""
    from tarot_pipeline import report as rp

    def make(balance, cost):
        return {
            "day": "2026-11-11", "start": "21:04", "pause": False,
            "user": "x", "balance_before": balance, "channels": 1, "scan_secs": 1,
            "candidates": 1, "submit_total": 0, "submit_ok": 0, "retry": [],
            "dup": 0, "live": [], "publish": [], "publish_fail": [],
            "errors": [], "elapsed_min": 1.0,
        }

    low = rp.render(make(795, 440), {}, 440, 0, 5, 0, 600, 450)
    assert "偏低" in low and "请提前充值" in low, low
    assert low.count("请提前充值") == 2, low
    ok = rp.render(make(2000, 440), {}, 440, 0, 5, 0, 600, 450)
    assert "偏低" not in ok and "请提前充值" not in ok, ok


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("%d failed" % len(FAILED))
    raise SystemExit(1 if FAILED else 0)
