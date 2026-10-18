# -*- coding: utf-8 -*-
r"""
把 src 里的修改部署成"外置补丁层"：

  1. 复制 src/**/*.py（不含 main.py）到安装目录 patch\，保持包结构；
  2. 用安装目录的 runtime python 预编译一遍，生成 __pycache__（首次启动不卡）；
  3. 把 WebView2Loader.dll 放到 bundle\（内建浏览器需要）；
  4. 不修改 exe —— exe 里只放过一次"外置补丁层"钩子（见 main.py），之后改代码
     只需重跑本脚本 + 重启程序。

用法：
    "D:\Bili23 Downloader\runtime\python.exe" tools\deploy_patch.py
    ... --dry-run       只打印将要复制的内容
    ... --install-dir "D:\Bili23 Downloader"
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")

DEFAULT_INSTALL = r"D:\Bili23 Downloader"
LOADER_SRC = os.path.join(ROOT, "poctest", "wv2sdk", "WebView2Loader.dll")


def copy_tree(src: str, dst: str, dry: bool):
    copied = 0
    total = 0

    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]

        for name in files:
            if not name.endswith(".py"):
                continue

            rel = os.path.relpath(os.path.join(root, name), src)

            if rel.replace("\\", "/") == "main.py":
                # 入口 main.py 必须留在 exe 里（补丁层钩子本身就在它里面）
                continue

            target = os.path.join(dst, rel)
            total += 1

            if dry:
                continue

            os.makedirs(os.path.dirname(target), exist_ok = True)
            shutil.copy2(os.path.join(root, name), target)
            copied += 1

    return total, copied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", default = DEFAULT_INSTALL)
    parser.add_argument("--dry-run", action = "store_true")
    args = parser.parse_args()

    install = args.install_dir
    patch = os.path.join(install, "patch")
    runtime_python = os.path.join(install, "runtime", "python.exe")
    bundle = os.path.join(install, "bundle")

    print("安装目录：", install)
    print("补丁目录：", patch)

    if not os.path.isdir(install):
        print("找不到安装目录")
        sys.exit(1)

    if not os.path.isdir(SRC):
        print("找不到源码目录：", SRC)
        sys.exit(1)

    # 1) 复制源码
    total, copied = copy_tree(SRC, patch, args.dry_run)
    print("源码文件：%d 个%s" % (total, "（dry-run，未复制）" if args.dry_run else "，已复制 %d 个" % copied))

    if args.dry_run:
        return

    # 1.5) 清掉 patch 目录里 src 已经不存在的文件（删模块时非常重要：
    #      否则旧模块还留在 patch 层，会被优先导入，表现为"删了没生效"）
    removed = 0

    if os.path.isdir(patch):
        for root, dirs, files in os.walk(patch):
            if os.path.basename(root) == "__pycache__":
                continue

            for name in files:
                if not name.endswith((".py", ".pyc")):
                    continue

                rel = os.path.relpath(os.path.join(root, name), patch)

                if rel.replace("\\", "/") == "main.py":
                    continue

                counterpart = os.path.join(SRC, rel)

                if not os.path.exists(counterpart):
                    os.remove(os.path.join(root, name))
                    removed += 1

        # 旧 __pycache__ 整体清掉重编，避免残留已删模块的 pyc
        import shutil as _shutil

        for root, dirs, files in os.walk(patch):
            for d in list(dirs):
                if d == "__pycache__":
                    _shutil.rmtree(os.path.join(root, d), ignore_errors = True)

    print("清理旧文件：", removed)

    # 2) 预编译（用目标 runtime，保证 pyc 魔数匹配）
    if os.path.exists(runtime_python):
        print("预编译 __pycache__ …")
        result = subprocess.run(
            [runtime_python, "-m", "compileall", "-q", patch],
            cwd = patch, stdout = subprocess.PIPE, stderr = subprocess.PIPE, text = True,
            encoding = "utf-8", errors = "replace"
        )

        if result.returncode != 0:
            print("预编译失败（不致命，首次启动会现场编译）：")
            print(result.stderr[-2000:])
        else:
            print("预编译完成")

    # 3) WebView2Loader.dll —— 必须放在安装目录之外：
    #    安装目录的完整性校验会把"多出来的文件"判成 Unexpected file 拒绝启动
    appdata = os.path.join(os.environ.get("APPDATA", ""), "Bili23 Downloader", "browser")
    os.makedirs(appdata, exist_ok = True)
    target_loader = os.path.join(appdata, "WebView2Loader.dll")

    if os.path.exists(LOADER_SRC):
        shutil.copy2(LOADER_SRC, target_loader)
        print("WebView2Loader.dll →", target_loader)
    else:
        print("警告：找不到 WebView2Loader.dll（内建浏览器将不可用）：", LOADER_SRC)

    # 如果之前误放进 bundle，清掉，避免完整性校验拦启动
    stale = os.path.join(install, "bundle", "WebView2Loader.dll")

    if os.path.exists(stale):
        os.remove(stale)
        print("已移除安装目录里的 WebView2Loader.dll（完整性校验不允许）")

    # 4) 清掉旧 pycache 之外的东西？不动，保持幂等
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(patch) for f in fs)
    print("补丁目录大小：%.1f MB" % (size / 1048576))
    print("部署完成。重启程序即可生效。")


if __name__ == "__main__":
    main()
