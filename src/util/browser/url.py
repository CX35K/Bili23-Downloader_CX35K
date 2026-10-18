# -*- coding: utf-8 -*-
"""内嵌浏览器用的 URL 工具：判断当前页面能不能丢给解析器"""

from ..common.data.url_pattern import url_patterns


def is_bilibili_url(url: str) -> bool:
    if not url:
        return False

    url = url.lower()

    return ("bilibili.com" in url) or ("b23.tv" in url) or ("bili2233.cn" in url)


def get_parser_type(url: str):
    """返回解析类型（video / bangumi / cheese / ...）；不支持时返回 None"""
    if not url:
        return None

    for parser_type, pattern in url_patterns:
        if pattern.search(url):
            return parser_type

    return None


def is_parseable(url: str) -> bool:
    return get_parser_type(url) is not None
