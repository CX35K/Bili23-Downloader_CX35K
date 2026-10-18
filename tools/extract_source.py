# -*- coding: utf-8 -*-
"""
从 Bili23 Downloader 的安装 exe 里提取内嵌的应用源码（PyStand app blob）。

背景：
    Bili23.exe 是 PyStand 启动器。exe 里嵌了一份 zip，包含 main.py / gui / util /
    res 的 .py 与 .pyc；启动时启动器把这份 zip 的内存地址塞进环境变量
    PYSTAND_APP_BLOB，再由内嵌的引导脚本用自定义 import hook 从内存 zip 加载模块。
    所以"源码"其实完整地躺在 exe 里，可以原样抠出来编辑。

用法：
    python extract_source.py --exe "D:\\Bili23 Downloader\\Bili23.exe" --out .\\src

    --exe    安装目录里的 Bili23.exe（也可指向 sandbox 里的副本）
    --out    输出目录（默认当前目录下 src）
    --manifest 额外输出一份清单（文件名、大小、sha256）
"""

import argparse
import hashlib
import io
import json
import os
import sys
import zipfile


def find_embedded_zip(data: bytes):
    """在 exe 里定位内嵌 zip：逐个候选中央目录起点试，第一个能完整解析的就是。"""
    candidates = []
    index = data.find(b"PK\x03\x04")

    while index >= 0:
        candidates.append(index)
        index = data.find(b"PK\x03\x04", index + 1)

    for offset in candidates:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data[offset:]))
            names = archive.namelist()
        except Exception:
            continue

        if names and any(name.endswith(".py") for name in names):
            return offset, archive

    raise RuntimeError("没有在 exe 中找到内嵌的应用 zip")


def extract(exe_path: str, out_dir: str, manifest_path: str = None):
    data = open(exe_path, "rb").read()

    offset, archive = find_embedded_zip(data)

    names = archive.namelist()

    # 内嵌 zip 的结束位置 = 中央目录结束记录 + 22 字节（无注释）
    end_of_central_directory = data.rfind(b"PK\x05\x06", offset)

    if end_of_central_directory < 0:
        raise RuntimeError("找不到 zip 的中央目录结束记录")

    blob_end = end_of_central_directory + 22

    print("exe          : %s (%d bytes)" % (exe_path, len(data)))
    print("zip 起点     : %d" % offset)
    print("zip 结束     : %d" % blob_end)
    print("blob 容量    : %d bytes (%.2f MB)" % (blob_end - offset, (blob_end - offset) / 1048576))
    print("条目数       : %d" % len(names))

    os.makedirs(out_dir, exist_ok=True)

    items = []

    for name in names:
        payload = archive.read(name)
        target = os.path.join(out_dir, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)

        with open(target, "wb") as f:
            f.write(payload)

        items.append({
            "name": name,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })

    py_count = sum(1 for i in items if i["name"].endswith(".py"))

    print("已解出       : %d 个文件（其中 .py %d 个）" % (len(items), py_count))

    if manifest_path:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"exe": exe_path, "blob_offset": offset, "blob_end": blob_end, "entries": items}, f, ensure_ascii=False, indent=2)

        print("清单         : %s" % manifest_path)

    return offset, blob_end


def main():
    parser = argparse.ArgumentParser(description="从 Bili23 Downloader 的 exe 提取内嵌源码")
    parser.add_argument("--exe", default=r"D:\Bili23 Downloader\Bili23.exe")
    parser.add_argument("--out", default="src")
    parser.add_argument("--manifest", default=None)

    args = parser.parse_args()

    extract(args.exe, args.out, args.manifest)


if __name__ == "__main__":
    main()
