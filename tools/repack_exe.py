# -*- coding: utf-8 -*-
"""
把修改后的源码重新打包进 Bili23.exe（回填 PyStand 内嵌 app blob）。

⚠️ 重要限制
    1. 只能"同长度覆盖"：PyStand 启动器从资源里拿到的 blob 大小是固定的，
       回填后的 zip 必须 ≤ 原 blob 容量（本机 2.20.0 版本为 1,822,166 字节）。
       超出时本脚本会报错；可加 --strip-pyc（丢掉 .pyc，只留 .py）来瘦身，
       代价是首次导入要从源码编译，启动慢一点，但功能一致。
    2. 回填后 exe 的 Authenticode 数字签名失效（Windows 可能弹 SmartScreen 提示）。
    3. 官方自动更新会覆盖 exe，改动随之丢失。

稳妥做法（推荐）：先用 launcher.py 从源码目录跑通改动，确认无误再回填。

用法：
    # 只检查能不能装下、生成 zip 到 build/（不碰 exe）
    runtime\\python.exe tools\\repack_exe.py --src src --exe sandbox\\Bili23.exe

    # 真正回填（自动备份原 exe 为 .bak）
    runtime\\python.exe tools\\repack_exe.py --src src --exe sandbox\\Bili23.exe --apply

注意：请用安装目录里的 runtime\\python.exe 运行本脚本（版本 3.13，pyc magic 才匹配）。
"""

import argparse
import importlib.util
import io
import marshal
import os
import shutil
import struct
import sys
import time
import zipfile

END_OF_CENTRAL_DIRECTORY = b"PK\x05\x06"

# 补齐用的占位文件：内嵌 zip 末尾需要贴近 blob 容量，否则 Python zipfile
# 在最后 64KB 内找不到中央目录结束记录。这里用一个不压缩的占位条目吃掉空隙。
PAD_NAME = "__pad__.bin"


def find_embedded_zip(data: bytes):
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
            end = data.rfind(END_OF_CENTRAL_DIRECTORY, offset)

            if end < 0:
                continue

            return offset, end + 22, archive

    raise RuntimeError("没有在 exe 中找到内嵌的应用 zip")


def make_pyc(source_path: str):
    """按"魔数 + 0 标志 + mtime + size"的 16 字节头格式生成 pyc，与 PyStand loader 的
    marshal.loads(data[16:]) 对齐。"""
    source = open(source_path, "rb").read()
    code = compile(source, source_path, "exec")
    mtime = int(os.path.getmtime(source_path))
    header = importlib.util.MAGIC_NUMBER + b"\x00\x00\x00\x00" + struct.pack("<II", mtime & 0xFFFFFFFF, len(source) & 0xFFFFFFFF)
    return header + marshal.dumps(code)


def build_zip(src_dir: str, names, strip_pyc: bool, pad_payload: int = 0):
    """按原始 zip 的条目顺序重建，保证 loader 的模块表与原来一致。

    pad_payload > 0 时追加一个不压缩的占位条目，用来把 zip 长度精确顶到目标值
    （见 fit_to_capacity 的说明）。
    """
    buffer = io.BytesIO()
    archive = zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9)

    missing = []

    for name in names:
        if strip_pyc and name.endswith(".pyc"):
            continue

        path = os.path.join(src_dir, name.replace("/", os.sep))

        if name.endswith(".pyc"):
            source_path = path[:-1]

            if os.path.exists(source_path):
                archive.writestr(name, make_pyc(source_path))

        elif name.endswith(".py"):
            if os.path.exists(path):
                archive.writestr(name, open(path, "rb").read())
            else:
                # 模块已被删除（例如整个更新模块被移除了）：
                # 直接跳过，不再视为错误——只要源码里没有任何地方再 import 它即可
                missing.append(name)

        else:
            # 非源码条目（当前版本没有，保留兼容）
            if os.path.exists(path):
                archive.writestr(name, open(path, "rb").read())

    if pad_payload > 0:
        archive.writestr(zipfile.ZipInfo(PAD_NAME), b"\x00" * pad_payload, compress_type=zipfile.ZIP_STORED)

    archive.close()

    if missing:
        print("提示：以下源码文件已删除，不再打包进 exe（请确认没有残留 import）：")
        print("  " + ", ".join(missing))

    if "main.py" in missing:
        raise RuntimeError("入口 main.py 缺失，无法打包")

    return buffer.getvalue()


def fit_to_capacity(src_dir: str, names, capacity: int, strip_pyc: bool):
    """把 zip 长度精确调整到 capacity。

    为什么必须"精确"：PyStand 用固定大小的内存资源传给 zipfile，而 exe 里这份
    嵌入 zip 后面还跟着 65KB 左右的其它数据（.rsrc 剩余部分 + 签名）。Python 的
    zipfile 只在文件末尾 64KB 内找中央目录结束记录，所以 zip 的 EOCD 必须落在
    blob 末尾附近 —— 留几万个 0 当填充会让程序直接报 "File is not a zip file"。
    这里用不压缩的占位条目把长度顶到和原 blob 完全一致。
    """
    base = build_zip(src_dir, names, strip_pyc)

    if len(base) > capacity:
        return None, len(base)

    payload = 0

    for _ in range(6):
        blob = build_zip(src_dir, names, strip_pyc, pad_payload = payload)

        delta = capacity - len(blob)

        if delta == 0:
            return blob, 0

        if delta < 0:
            payload -= (-delta) + 64
        else:
            payload += delta

        payload = max(0, payload)

    return None, len(base)



def main():
    parser = argparse.ArgumentParser(description="把源码回填进 Bili23.exe 内嵌 app blob")
    parser.add_argument("--src", default="src")
    parser.add_argument("--exe", default=r"sandbox\Bili23.exe")
    parser.add_argument("--apply", action="store_true", help="真正写入 exe（默认只检查）")
    parser.add_argument("--strip-pyc", action="store_true", help="丢弃 .pyc 条目以缩小体积")
    parser.add_argument("--out-zip", default=None, help="把生成的 zip 另存一份便于检查")

    args = parser.parse_args()

    if sys.version_info[:2] != (3, 13):
        print("⚠️ 警告：当前解释器是 %s，目标运行时是 3.13，生成的 .pyc 魔数不匹配，"
              "loader 会退回编译 .py 源码（能用但略慢）。建议用安装目录的 runtime\\python.exe 运行本脚本。"
              % sys.version.split()[0])

    data = open(args.exe, "rb").read()

    offset, blob_end, archive = find_embedded_zip(data)
    capacity = blob_end - offset
    names = archive.namelist()

    print("目标 exe   : %s" % args.exe)
    print("blob 范围  : [%d, %d)  容量 %d bytes" % (offset, blob_end, capacity))

    blob, base_length = fit_to_capacity(args.src, names, capacity, args.strip_pyc)

    if blob is None:
        print("❌ 新源码打包后仍然超过容量，无法同长度回填（无填充时 %d bytes，容量 %d）。" % (base_length, capacity))
        print("   → 试加 --strip-pyc，或减少改动体积（本版本容量只有 %.2f MB）。" % (capacity / 1048576))
        sys.exit(1)

    assert len(blob) == capacity

    check = zipfile.ZipFile(io.BytesIO(blob))
    print("新 zip 条目: %d（原 %d），%s 占位" % (len(check.namelist()), len(names), PAD_NAME if PAD_NAME in check.namelist() else "无"))
    print("新 zip 校验: %d 个条目可读，长度 %d == 容量 %d" % (len(check.namelist()), len(blob), capacity))

    if args.out_zip:
        open(args.out_zip, "wb").write(blob)
        print("已写出     : %s" % args.out_zip)

    if not args.apply:
        print("\n（未写入，加 --apply 才真正回填 exe）")
        return

    backup = args.exe + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(args.exe, backup)
    print("已备份原 exe: %s" % backup)

    patched = data[:offset] + blob + data[blob_end:]

    with open(args.exe, "wb") as f:
        f.write(patched)

    print("✅ 已回填：%s（签名失效，SmartScreen 可能提示）" % args.exe)

    # 简单自检：回填后的 exe 里还能解析出 zip
    verify = open(args.exe, "rb").read()
    offset2, blob_end2, archive2 = find_embedded_zip(verify)
    print("自检       : zip@%d 条目 %d 个，首条 %s" % (offset2, len(archive2.namelist()), archive2.namelist()[0]))


if __name__ == "__main__":
    main()
