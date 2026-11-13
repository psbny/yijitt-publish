# -*- coding: utf-8 -*-
"""文件简介：代理开关——启动/停止 waimian 里的 clash，并同步 Windows 系统代理，避免关掉代理后整机断网。"""
import ctypes
import os
import socket
import subprocess
import time

DEFAULT_EXE = r"C:\tools\clash\clash.exe"
DEFAULT_HOME = r"C:\tools\clash\config"
PORT = 7890
_PROXY_NAME = "clash.meta-windows-386.exe"

_OPT_SETTINGS_CHANGED = 39
_OPT_REFRESH = 37
_DETACHED = 0x00000008


def is_running(port=PORT):
    s = socket.socket()
    s.settimeout(0.6)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _set_sys_proxy(on):
    """只动 ProxyEnable，ProxyServer 保持原值。

    关代理时必须把 ProxyEnable 归零：否则系统代理还指向 7890 但没人监听，
    整台电脑会连国内网站都打不开。
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1 if on else 0)
        winreg.CloseKey(key)
    except Exception:
        pass
    try:
        ctypes.windll.wininet.InternetSetOptionW(0, _OPT_SETTINGS_CHANGED, 0, 0)
        ctypes.windll.wininet.InternetSetOptionW(0, _OPT_REFRESH, 0, 0)
    except Exception:
        pass


def start(exe=None, home=None, wait_sec=20, log=None):
    exe = exe or DEFAULT_EXE
    home = home or DEFAULT_HOME
    if is_running():
        return True
    if not os.path.exists(exe):
        if log:
            log("找不到 clash：%s" % exe)
        return False
    try:
        subprocess.Popen([exe, "-d", home], creationflags=_DETACHED,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        if log:
            log("启动 clash 失败：%s" % e)
        return False
    for _ in range(int(wait_sec * 2)):
        if is_running():
            return True
        time.sleep(0.5)
    if log:
        log("clash 启动超时（%ds）" % wait_sec)
    return False


def stop(log=None):
    """停 clash 并关系统代理。已经停了就只修正系统代理。"""
    if is_running():
        try:
            subprocess.run(["taskkill", "/F", "/IM", _PROXY_NAME],
                           capture_output=True, timeout=15)
        except Exception:
            pass
        time.sleep(0.5)
    _set_sys_proxy(False)
    alive = is_running()
    if alive and log:
        log("警告：clash 仍在监听 %d 端口，可能没权限结束它" % PORT)
    return not alive