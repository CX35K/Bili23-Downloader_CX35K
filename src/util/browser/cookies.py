# -*- coding: utf-8 -*-
"""
把应用 config.json 里的登录 Cookie 注入到内嵌浏览器

为什么用 JS 注入而不是 QWebEngineCookieStore / CookieManager：
  实测 Qt 的 cookieStore.setCookie() 在这个组合下静默无效（cookieAdded 一个事件都不发）；
  WebView2 的 ICoreWebView2CookieManager 要额外定义一大堆 COM 接口。
  而"页面里 document.cookie = ..." 最直接、跨内核通用，且已验证能把 api nav 变成已登录。

副作用：SESSDATA 会从 HttpOnly 变成普通 cookie（只影响这个内嵌浏览器内部）。
"""

import json
import logging

from ..common.config import config

logger = logging.getLogger(__name__)

COOKIE_KEYS = (
    "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5",
    "buvid3", "buvid4", "buvid_fp", "b_nut", "b_lsid",
    "bili_ticket", "bili_ticket_expires", "buvid_expires", "uuid",
    "is_login",
)


def get_cookie_payload() -> dict:
    payload = {}

    for key in COOKIE_KEYS:
        item = getattr(config, key, None)

        if item is None:
            continue

        try:
            value = config.get(item)

        except Exception:
            continue

        if value is None or value == "" or value is False:
            continue

        payload[key] = str(value)

    return payload


def build_inject_script(cookie_dict: dict = None) -> str:
    """生成一段 JS 语句：把所有 cookie 写到 .bilibili.com 上，并打一个标记"""

    payload = json.dumps(cookie_dict if cookie_dict is not None else get_cookie_payload(), ensure_ascii = False)

    return (
        "(() => {"
        "  const cookies = %s;"
        "  let count = 0;"
        "  for (const key of Object.keys(cookies)) {"
        "    try {"
        "      document.cookie = key + '=' + String(cookies[key])"
        "        + '; domain=.bilibili.com; path=/; secure; samesite=lax';"
        "      count += 1;"
        "    } catch (e) {}"
        "  }"
        "  window.__bili23_cookies_injected = count;"
        "  return count;"
        "})()"
    ) % payload


def build_login_probe_script() -> str:
    """在页面里问一次 api nav，把结果放到 window.__bili23_login 供轮询读取"""
    return (
        "window.__bili23_login = null;"
        "fetch('https://api.bilibili.com/x/web-interface/nav', {credentials: 'include'})"
        "  .then(r => r.json())"
        "  .then(d => { window.__bili23_login = {code: d.code, isLogin: !!(d.data && d.data.isLogin),"
        "    uname: (d.data && d.data.uname) || ''}; })"
        "  .catch(e => { window.__bili23_login = {error: String(e)}; });"
    )
