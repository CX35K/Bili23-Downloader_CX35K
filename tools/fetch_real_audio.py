# -*- coding: utf-8 -*-
"""下载一个真实的 B 站独立音频流（DASH fMP4 分片），供重封装回归测试使用。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BV = "BV1GJ411x7h7"
CID = 137649199
OUT = r"E:\Agents_Workspace\Bili23-GUI-2.20.0\_bugtest\real_audio.m4a"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"

headers = {
    "User-Agent": UA,
    "Referer": "https://www.bilibili.com/video/%s" % BV,
}

api = "https://api.bilibili.com/x/player/playurl?bvid=%s&cid=%s&qn=0&fnver=0&fnval=4048&fourk=1" % (BV, CID)
data = requests.get(api, headers=headers, timeout=20).json()

print("playurl code =", data.get("code"), data.get("message"))

dash = data["data"]["dash"]
audio_list = sorted(dash["audio"], key=lambda x: x["id"], reverse=True)

print("audio streams:", [a["id"] for a in audio_list])

target = next((a for a in audio_list if a["id"] == 30280), audio_list[0])

print("选中音质:", target["id"], "| host:", target["baseUrl"].split("/")[2])

response = requests.get(target["baseUrl"], headers=headers, timeout=120, stream=True)
response.raise_for_status()

with open(OUT, "wb") as f:
    for chunk in response.iter_content(262144):
        f.write(chunk)

import os

print("已保存:", OUT, os.path.getsize(OUT), "bytes")
