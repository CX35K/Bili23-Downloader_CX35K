# -*- coding: utf-8 -*-
r"""
音频重封装 / M4A→FLAC 选项 —— 回归验证脚本

三级验证：
  1. 命令级：FFmpegCommand.remux_audio / convert_m4a_to_flac 生成的命令能真正跑通
  2. 流程级：真实 Merger 走「仅音频下载」分支（假 TaskInfo，不写任务库），
     覆盖 remux、M4A→FLAC、M4A→MP3、FLAC/MP3 同时开启时的优先级
  3. 界面级：设置-下载-下载格式 里新选项存在、开关与配置双向绑定、能落盘

优先使用 _bugtest\real_audio.m4a（B 站真实下载的 DASH 音频分片），
没有时退回本地合成的 fMP4 样例（tools/fetch_real_audio.py 可重新抓取）。

全流程使用 offscreen 平台，不弹窗口，可无人值守运行：
    "D:\\Bili23 Downloader\\runtime\\python.exe" tools\\test_audio_remux.py
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # noqa: E402  必须在导入 Qt 之前

import json
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import launcher  # noqa: E402  复用它的 PYSTAND 环境与 sys.path 设置

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from util.common.enum import DownloadStatus, DownloadType  # noqa: E402
from util.common.config import config, config_path  # noqa: E402
from util.ffmpeg import init_ffmpeg, runtime as ffmpeg_runtime  # noqa: E402
from util.ffmpeg.command import FFmpegCommand  # noqa: E402
from util.download.task.info import TaskInfo  # noqa: E402

SAMPLE_DIR = os.path.join(ROOT, "_bugtest")
WORK_DIR = os.path.join(ROOT, "_bugtest", "merger_run")

# 真实的 B 站 DASH 音频分片优先；缺失时用本地合成的 fMP4 样例
REAL_AUDIO = os.path.join(SAMPLE_DIR, "real_audio.m4a")
M4A_SAMPLE = REAL_AUDIO if os.path.exists(REAL_AUDIO) else os.path.join(SAMPLE_DIR, "dash_audio.m4a")

FFMPEG = os.path.join(os.environ["PYSTAND_HOME"], "bundle", "ffmpeg.exe")

# 校验 FLAC 成品需要一个带 flac 解复用器的 ffmpeg：
# 内置裁剪版没有 flac demuxer（只能写不能读），用它校验只会得到
# "Invalid data found when processing input" 的假失败
PROBE_FFMPEG = FFMPEG

PASS = []
FAIL = []


def find_probe_ffmpeg():
    """挑一个能读 flac 的 ffmpeg 用于校验产物，找不到就退回内置版"""
    global PROBE_FFMPEG

    candidates = [
        r"D:\FormatFactory\ffmpeg.exe",
        r"D:\Program Files\JianyingPro\6.6.0.12149\ffmpeg.exe",
    ]

    for candidate in candidates:
        if not os.path.exists(candidate):
            continue

        try:
            result = run_command([candidate, "-hide_banner", "-demuxers"], os.path.dirname(candidate))

        except OSError:
            continue

        if any(line.strip().startswith("D") and " flac " in line for line in result.stdout.splitlines()):
            PROBE_FFMPEG = candidate
            return

    PROBE_FFMPEG = FFMPEG


def parse_duration(text: str):
    import re

    match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2})\.(\d+)", text or "")

    if not match:
        return None

    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3))

    return hours * 3600 + minutes * 60 + seconds


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


def run_command(cmd, cwd):
    return subprocess.run(cmd, cwd = cwd, stdout = subprocess.PIPE, stderr = subprocess.PIPE, text = True, encoding = "utf-8", errors = "replace")


def probe(path, ffmpeg: str = None):
    return run_command([ffmpeg or FFMPEG, "-hide_banner", "-i", path], os.path.dirname(path))


def test_command_level():
    print("\n== 1. 命令级 ==")

    print("-- remux_audio（独立音频流重封装）")

    cases = [
        (M4A_SAMPLE, "out_m4a.m4a", dict(output_format = "mp4", faststart = True), "aac"),
        (os.path.join(SAMPLE_DIR, "dash_flac.m4a"), "out_flac.flac", dict(output_format = "flac", faststart = False), "flac"),
        (os.path.join(SAMPLE_DIR, "dash_ec3b.m4a"), "out_ec3_fallback.m4a", dict(output_format = "mp4", faststart = True), "eac3"),
    ]

    for source, output, kwargs, expect_codec in cases:
        if not os.path.exists(source):
            check(os.path.basename(source) + "（样例缺失，跳过）", True)
            continue

        out = os.path.join(WORK_DIR, output)

        if os.path.exists(out):
            os.remove(out)

        cmd = FFmpegCommand.remux_audio(input_path = source, output_path = out, **kwargs).build()
        print("    $ " + " ".join(cmd))

        result = run_command(cmd, WORK_DIR)

        ok = result.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
        check("remux %s -> %s" % (os.path.basename(source), output), ok, (result.stderr or "")[-300:])

        if ok:
            info = probe(out, PROBE_FFMPEG if expect_codec == "flac" else None)
            check("  输出含 %s 流" % expect_codec, expect_codec in (info.stderr + info.stdout), (info.stderr or "")[-200:])

    print("-- convert_m4a_to_flac（新选项用到的转换命令）")

    if os.path.exists(M4A_SAMPLE):
        out = os.path.join(WORK_DIR, "out_convert.flac")

        if os.path.exists(out):
            os.remove(out)

        cmd = FFmpegCommand.convert_m4a_to_flac(input_path = M4A_SAMPLE, output_path = out).build()
        print("    $ " + " ".join(cmd))

        result = run_command(cmd, WORK_DIR)

        ok = result.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
        check("M4A -> FLAC 转换", ok, (result.stderr or "")[-300:])

        if ok:
            info = probe(out, PROBE_FFMPEG)
            check("  输出含 flac 流", "Audio: flac" in (info.stderr + info.stdout), (info.stderr or "")[-200:])

            source_duration = parse_duration(probe(M4A_SAMPLE, PROBE_FFMPEG).stderr)
            output_duration = parse_duration(info.stderr)

            check(
                "  时长与源一致（%s -> %s 秒）" % (source_duration, output_duration),
                source_duration is not None and output_duration is not None and abs(source_duration - output_duration) <= 1
            )


def make_task_info(task_id: str, audio_ext: str, folder: str, **options) -> TaskInfo:
    task = TaskInfo()

    task.Basic.task_id = task_id
    task.Basic.show_title = "测试音频"

    task.File.download_path = WORK_DIR
    task.File.folder = folder
    task.File.name = "测试音频"
    task.File.audio_file_ext = audio_ext
    task.File.relative_files = ["audio_%s.%s" % (task_id, audio_ext)]

    task.Download.type = int(DownloadType.AUDIO)
    task.Download.merge_video_audio = False
    task.Download.keep_original_files = False
    task.Download.video_parts_count = 0
    task.Download.status = DownloadStatus.DOWNLOADING

    # 任务级选项快照，与真实任务创建时 _OPTION_SPEC 固化的字段一致
    for key, value in options.items():
        setattr(task.Options, key, value)

    return task


def run_merger_case(name: str, task_id: str, audio_ext: str, sample: str, expected_ext: str, app: QApplication, **options):
    folder = "case_" + task_id
    case_dir = os.path.join(WORK_DIR, folder)

    shutil.rmtree(case_dir, ignore_errors = True)
    os.makedirs(case_dir, exist_ok = True)

    temp_name = "audio_%s.%s" % (task_id, audio_ext)
    shutil.copy2(sample, os.path.join(case_dir, temp_name))

    from util.download.downloader.merger import Merger

    task = make_task_info(task_id, audio_ext, folder, **options)
    merger = Merger(task)
    merger.start()

    state = {"done": False}

    def poll():
        if task.Download.status in (DownloadStatus.COMPLETED, DownloadStatus.FFMPEG_FAILED):
            state["done"] = True
            app.quit()

    from PySide6.QtCore import QTimer

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(100)

    QTimer.singleShot(60000, app.quit)
    app.exec()
    timer.stop()

    files = sorted(os.listdir(case_dir))
    print("    最终目录：%s" % files)

    expected_file = "测试音频.%s" % expected_ext

    ok = (
        state["done"]
        and task.Download.status == DownloadStatus.COMPLETED
        and expected_file in files
        and temp_name not in files
    )

    check("Merger 仅音频流程（%s）" % name, ok)

    if expected_file in files:
        info = probe(os.path.join(case_dir, expected_file), PROBE_FFMPEG if expected_ext == "flac" else None)
        check("  成品可解析", "Audio:" in (info.stderr + info.stdout), (info.stderr or "")[-200:])

        if expected_ext == "flac":
            check("  成品为 flac 编码", "Audio: flac" in (info.stderr + info.stdout), (info.stderr or "")[-200:])


def test_merger_level(app: QApplication):
    print("\n== 2. 流程级：Merger 的「仅音频下载」分支 ==")

    from util.download.task.manager import task_manager

    # 假任务不该写进用户真实的任务库/已完成列表
    task_manager.update = lambda *a, **k: None
    task_manager.mark_as_completed = lambda *a, **k: None

    if not os.path.exists(M4A_SAMPLE):
        check("真实/合成的 fMP4 音频样例缺失，跳过流程级验证", False)
        return

    run_merger_case("m4a 默认重封装", "m4adefault", "m4a", M4A_SAMPLE, "m4a", app)

    ec3 = os.path.join(SAMPLE_DIR, "dash_ec3b.m4a")

    if os.path.exists(ec3):
        run_merger_case("ec3 降级到 mp4", "ec3fallback", "ec3", ec3, "m4a", app)

    run_merger_case("M4A→FLAC", "flacopt", "m4a", M4A_SAMPLE, "flac", app, m4a_to_flac = True)

    run_merger_case("同时开启 FLAC/MP3（FLAC 优先）", "bothopt", "m4a", M4A_SAMPLE, "flac", app, m4a_to_flac = True, m4a_to_mp3 = True)

    run_merger_case("M4A→MP3（旧选项未受影响）", "mp3opt", "m4a", M4A_SAMPLE, "mp3", app, m4a_to_mp3 = True)


def test_ui_level(app: QApplication):
    print("\n== 3. 界面级：设置-下载-下载格式 新选项 ==")

    from gui.component.setting.card import DownloadFormatCard
    from gui.component.setting.widget import SettingSwitchButton

    card = DownloadFormatCard(None)
    app.processEvents()

    switch = getattr(card, "m4a_to_flac_switch", None)

    check(
        "设置卡片包含 M4A→FLAC 开关且绑定 config.m4a_to_flac",
        isinstance(switch, SettingSwitchButton) and switch.config_item is config.m4a_to_flac
    )

    labels = [widget.text() for widget in card.findChildren(QLabel)]
    check("卡片里有 FLAC 文案", any("FLAC" in text for text in labels), str([t for t in labels if t][:6]))
    check("旧的 M4A→MP3 选项仍在", any("MP3" in text for text in labels))

    # 开关 ↔ 配置 双向绑定 + 落盘
    original = config.get(config.m4a_to_flac)

    switch.setChecked(not original)
    app.processEvents()

    toggled = config.get(config.m4a_to_flac) == (not original)
    check("拨动开关即写入配置", toggled)

    try:
        data = json.load(open(config_path, encoding = "utf-8"))
        persisted = data.get("Download", {}).get("m4a_to_flac") == (not original)
    except Exception as e:    # noqa: BLE001
        persisted = False
        print("    读取 config.json 失败：", e)

    check("配置已落盘到 config.json", persisted)

    # 恢复原值，别留下副作用
    switch.setChecked(original)
    app.processEvents()

    check("恢复原值", config.get(config.m4a_to_flac) == original)

    # 布局回归（文案长度）：那行小字是单行 QLabel，写长了会把右侧开关顶出可视区域（曾发生过）。
    # 这里断言"文案足够短、细节交给 tooltip"；像素级检查在 tools/capture_setting_card.py
    # （它在 700px 宽下断言开关不越界，并能用 --legacy-long 自检确实抓得到这个回归）
    descriptions = [
        widget for widget in card.findChildren(QLabel)
        if widget.text().startswith(("仅下载", "Only applies to audio"))
    ]

    check("FLAC 说明文案存在", bool(descriptions))

    if descriptions:
        text = descriptions[0].text()

        check("说明文案足够短（<= 40 字符）", len(text) <= 40, "%d 字符：%s" % (len(text), text))
        check("详细说明放在 tooltip 里", "不会提升音质" in descriptions[0].toolTip(), descriptions[0].toolTip()[:50])


def main():
    os.makedirs(WORK_DIR, exist_ok = True)

    app = QApplication(sys.argv)

    init_ffmpeg()
    find_probe_ffmpeg()

    print("ffmpeg  =", ffmpeg_runtime.ffmpeg.executable)
    print("muxers  =", ", ".join(sorted(ffmpeg_runtime.ffmpeg.muxers)) or "(未探测到)")
    print("probe   =", PROBE_FFMPEG)
    print("platform=", app.platformName())

    test_command_level()
    test_merger_level(app)
    test_ui_level(app)

    print("\n== 汇总 ==")
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))

    if FAIL:
        print("失败项：" + ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
