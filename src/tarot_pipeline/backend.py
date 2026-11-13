# -*- coding: utf-8 -*-
r"""文件简介：内容平台后台 HTTP 客户端。

所有端点都是 2026-11-04 从线上前端 JS 逆向确认的，不是猜的：
  GET  /api/user/info                     余额、昵称
  GET  /api/post/aitask/free              免费提交剩余次数
  GET  /api/post/aitask?current=&pageSize= AI 字幕任务列表（含 submit.chapter / file_hash）
  POST /api/post/aitask/submit            multipart: title, chapter, file, request_id, file_hash, force?
  GET  /api/post/detail?id=               文章详情
  POST /api/post/tarot/upsert             保存 / 发布文章
  GET  /api/post/series?page_size=        频道列表
  GET  /api/post/series/match?title=      按标题自动匹配频道
  POST /api/tool/upload                   FormData: file, compressed=1 -> url
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import string
import time
import uuid
from typing import Any

import requests

BASE = "https://admin.example.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class BackendError(RuntimeError):
    pass


class AuthError(BackendError):
    pass


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Client:
    def __init__(self, cookie_file: str, timeout: int = 60, log=print):
        self.timeout = timeout
        self.log = log
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": BASE + "/tarot",
                               "Accept": "application/json, text/plain, */*"})
        self._load_cookie(cookie_file)

    def _load_cookie(self, cookie_file: str) -> None:
        if not os.path.exists(cookie_file):
            raise AuthError("找不到 cookie 文件：%s（先跑 fetch_cookie.mjs）" % cookie_file)
        with open(cookie_file, encoding="utf-8-sig") as f:
            ck = json.load(f).get("cookies") or {}
        if "session_id" not in ck:
            raise AuthError("cookie 文件里没有 session_id")
        for k, v in ck.items():
            self.s.cookies.set(k, v, domain="admin.example.com")

    # ---------------------------------------------------------- 基础
    def _req(self, method: str, path: str, **kw) -> dict:
        url = BASE + path
        r = self.s.request(method, url, timeout=self.timeout, **kw)
        if r.status_code >= 500:
            raise BackendError("服务端 %s %s" % (r.status_code, path))
        try:
            j = r.json()
        except ValueError:
            raise BackendError("%s 返回非 JSON（可能是登录页）：%s" % (path, r.text[:120]))
        if j.get("code") == 400 and "登录" in str(j.get("msg", "")):
            raise AuthError("cookie 失效，需要重新扫码导出")
        return j

    def _data(self, method: str, path: str, **kw) -> Any:
        j = self._req(method, path, **kw)
        if j.get("code") != 0:
            raise BackendError("%s -> code=%s msg=%s" % (path, j.get("code"), j.get("msg")))
        return j.get("data")

    # ---------------------------------------------------------- 账号
    def user_info(self) -> dict:
        return self._data("GET", "/api/user/info") or {}

    def balance(self) -> int:
        return int(self.user_info().get("balance") or 0)

    def free_quota(self) -> int:
        d = self._data("GET", "/api/post/aitask/free") or {}
        return int(d.get("free_submissions") or 0)

    # ---------------------------------------------------------- 任务
    def list_tasks(self, page_size: int = 50) -> list[dict]:
        d = self._data("GET", "/api/post/aitask", params={"current": 1, "pageSize": page_size})
        if isinstance(d, dict):
            return d.get("list") or d.get("data") or []
        return d or []

    def find_by_hash(self, file_hash: str) -> dict | None:
        for t in self.list_tasks(200):
            if (t.get("submit") or {}).get("file_hash") == file_hash:
                return t
        return None

    def get_task(self, task_id: int) -> dict | None:
        for t in self.list_tasks(200):
            if int(t.get("id", 0)) == int(task_id):
                return t
        return None

    def submit_srt(self, title: str, chapter: str, srt_path: str, force: bool = False) -> dict:
        """提交字幕任务。成功返回 {code:0,...}；429 表示同一文件已提交过。"""
        fhash = md5_file(srt_path)
        form = {
            "request_id": str(uuid.uuid4()),
            "file_hash": fhash,
        }
        if title:
            form["title"] = title
        if chapter:
            form["chapter"] = chapter
        if force:
            form["force"] = "true"
        with open(srt_path, "rb") as f:
            files = {"file": (os.path.basename(srt_path), f, "text/plain")}
            j = self._req("POST", "/api/post/aitask/submit", data=form, files=files)
        j["_file_hash"] = fhash
        return j

    def wait_task(self, task_id: int, timeout: int = 1200, interval: int = 20) -> dict:
        """等 AI 处理完，返回最新 task 记录（含 post_id）。"""
        waited = 0
        while waited <= timeout:
            t = self.get_task(task_id)
            if t and t.get("status") in ("completed", "failed", "error"):
                return t
            time.sleep(interval)
            waited += interval
        t = self.get_task(task_id)
        if t is None:
            raise BackendError("任务 %s 在列表里找不到" % task_id)
        return t

    # ---------------------------------------------------------- 文章
    def get_post(self, post_id: int) -> dict:
        return self._data("GET", "/api/post/detail", params={"id": post_id}) or {}

    def list_posts(self, title: str = "", page_size: int = 100, category: int = 1) -> list[dict]:
        """列文章。注意必须带 category=1，否则后台返回空数组（实测）。"""
        params = {"current": 1, "pageSize": page_size, "category": category}
        if title:
            params["title"] = title
        d = self._data("GET", "/api/post/list", params=params)
        if isinstance(d, dict):
            return d.get("data") or d.get("list") or []
        return d or []

    def list_all_posts(self, page_size: int = 100, max_pages: int = 30) -> list[dict]:
        """翻页拉全部文章（排期避让用）。"""
        out = []
        for page in range(1, max_pages + 1):
            d = self._data("GET", "/api/post/list",
                           params={"current": page, "pageSize": page_size, "category": 1})
            rows = (d or {}).get("data") or []
            if not rows:
                break
            out.extend(rows)
            if len(rows) < page_size:
                break
        return out

    def series_map(self) -> dict[str, int]:
        """频道中文名 -> series_id。"""
        d = self._data("GET", "/api/post/series", params={"current": 1, "pageSize": 200})
        lst = d.get("list") if isinstance(d, dict) else d
        if isinstance(d, dict):
            lst = d.get("data") or []
        out = {}
        for it in lst or []:
            t = (it.get("title") or "").strip()
            if t:
                out[t.strip("【】 ") if t.startswith("【") else t] = it.get("id")
        return out

    def match_series(self, title: str) -> dict:
        return self._data("GET", "/api/post/series/match", params={"title": title}) or {}

    def attach_series(self, post_id: int, series_id: int, action: str = "add") -> dict:
        """把文章挂到频道。前端保存文章后就是单独调这个接口。"""
        return self._req("POST", "/api/post/series/post",
                         json={"post_id": int(post_id), "series_id": int(series_id),
                               "action": action})

    def resolve_series_id(self, title: str):
        """按标题前缀匹配频道 id，匹配不到返回 None。"""
        try:
            j = self.match_series(title)
        except Exception:
            return None
        if isinstance(j, dict):
            if j.get("id"):
                return int(j["id"])
            d = j.get("data")
            if isinstance(d, dict) and d.get("id"):
                return int(d["id"])
            if isinstance(d, list) and d and isinstance(d[0], dict) and d[0].get("id"):
                return int(d[0]["id"])
        return None

    def upload(self, path: str, compressed: bool = True) -> str:
        import mimetypes
        _ct = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            files = {"file": (os.path.basename(path), f, _ct)}
            data = {"compressed": "1"} if compressed else {}
            j = self._req("POST", "/api/tool/upload", data=data, files=files)
        # v2 (m03413)：必须显式带 Content-Type，否则 requests 默认 application/octet-stream，
        # OSS 存成 octet-stream 后部分客户端（小程序）不渲染原图。
        # 实测返回是扁平的：{"name":"low","status":"success","url":"https://...png/low"}
        if j.get("status") not in (None, "success") or j.get("code") not in (None, 0):
            raise BackendError("上传失败：%s" % (j.get("msg") or j))
        url = j.get("url") or ((j.get("data") or {}) or {}).get("url")
        if not url:
            raise BackendError("上传返回里没有 url：%s" % j)
        return url

    def upsert_post(self, body: dict) -> dict:
        j = self._req("POST", "/api/post/tarot/upsert", json=body)
        return j
