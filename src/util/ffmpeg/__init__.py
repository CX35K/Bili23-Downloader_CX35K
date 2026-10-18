from ..common.io.directory import Directory
from ..common.enum import FFmpegSource
from ..common.config import config
from ..common.runtime import runtime

from pathlib import Path
import logging
import shutil
import re
import subprocess
import sys
import os

logger = logging.getLogger(__name__)

# `ffmpeg -muxers` 的输出形如 "  E  mp4    MP4 (MPEG-4 Part 14)"
_MUXER_PATTERN = re.compile(r"^\s*E\s+(\S+)")

# 确定不同平台 FFmpeg 可执行文件名
if sys.platform == "win32":
    ffmpeg_executable = "ffmpeg.exe"

else:
    ffmpeg_executable = "ffmpeg"

bundle_ffmpeg_path = None

_initialized = False

def set_ffmpeg_environment(path: str):
    os.environ["PATH"] = str(Path(path).parent) + os.pathsep + os.environ["PATH"]

    logger.info(f"已将 FFmpeg 路径 {path} 添加到环境变量")

    runtime.ffmpeg.unavailable = False

def try_system_ffmpeg():
    ffmpeg_path = shutil.which(ffmpeg_executable)

    if ffmpeg_path:
        logger.info(f"环境变量中找到 FFmpeg 可执行文件：{ffmpeg_path}")
        set_ffmpeg_environment(ffmpeg_path)
        return True
    
    logger.warning("环境变量中未找到 FFmpeg 可执行文件")
    return False

def try_bundled_ffmpeg():
    if runtime.ffmpeg.bundle_exist:
        logger.info(f"找到附带的 FFmpeg 可执行文件：{bundle_ffmpeg_path}")
        set_ffmpeg_environment(bundle_ffmpeg_path)
        return True

    logger.warning("没有找到附带的 FFmpeg 可执行文件")
    return False

def get_bundle_ffmpeg_path():
    return Directory.get_cwd() / "bundle" / ffmpeg_executable

def on_ffmpeg_not_found():
    logger.error("没有可用的 FFmpeg 可执行文件")
    runtime.ffmpeg.unavailable = True
    return False

def init_ffmpeg():
    # 探测 FFmpeg 需要扫描 PATH 与安装目录，属于磁盘 IO。此前该逻辑写在模块顶层，
    # 任何一次 util 子模块导入都会连带执行，白白占用启动的关键路径，现改为显式调用。
    global bundle_ffmpeg_path, _initialized

    if _initialized:
        return

    _initialized = True

    runtime.ffmpeg.executable = ffmpeg_executable

    bundle_ffmpeg_path = get_bundle_ffmpeg_path()
    runtime.ffmpeg.bundle_exist = bundle_ffmpeg_path.exists()

    match config.get(config.ffmpeg_source):
        case FFmpegSource.BUNDLED:
            if not try_bundled_ffmpeg():
                logger.warning("附带的 FFmpeg 不存在，将尝试使用环境变量中的 FFmpeg")

                if try_system_ffmpeg():
                    config.set(config.ffmpeg_source, FFmpegSource.SYSTEM)
                else:
                    on_ffmpeg_not_found()

        case FFmpegSource.SYSTEM:
            if not try_system_ffmpeg():
                logger.warning("环境变量中无 FFmpeg，将尝试使用附带的 FFmpeg")

                if try_bundled_ffmpeg():
                    config.set(config.ffmpeg_source, FFmpegSource.BUNDLED)
                else:
                    on_ffmpeg_not_found()

        case FFmpegSource.CUSTOM:
            custom_ffmpeg_path = Path(config.get(config.custom_ffmpeg_path))

            if custom_ffmpeg_path.exists():
                set_ffmpeg_environment(custom_ffmpeg_path)
            else:
                logger.warning(f"自定义 FFmpeg 路径无效：{custom_ffmpeg_path}，将尝试 fallback")

                if try_bundled_ffmpeg():
                    config.set(config.ffmpeg_source, FFmpegSource.BUNDLED)

                elif try_system_ffmpeg():
                    config.set(config.ffmpeg_source, FFmpegSource.SYSTEM)

                else:
                    on_ffmpeg_not_found()

    if not runtime.ffmpeg.unavailable:
        runtime.ffmpeg.muxers = probe_supported_muxers()


def probe_supported_muxers() -> set:
    """
    查询当前生效的 FFmpeg 支持哪些封装器

    这一步是「独立音频流重封装」修复的前提：安装包内置的 FFmpeg 是裁剪版，
    编译时只开了 mp4/flv/mp3/flac/matroska/mov，**没有 m4a(ipod) 与 eac3**。
    而重封装原先只给输出文件名、让 FFmpeg 按扩展名猜容器，遇到 .m4a/.ec3 时
    直接报 "Unable to choose an output format" / "Error initializing the muxer"，
    表现就是下载独立音频流必失败。拿到封装器清单后即可显式 -f 并做降级判断。

    探测失败（老版本 FFmpeg 不支持 -muxers、进程被拦等）返回空集合，调用方据此
    退回旧的「按扩展名猜容器」行为，不会比修复前更差。
    """
    try:
        kwargs = {}

        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        result = subprocess.run(
            [ffmpeg_executable, "-hide_banner", "-muxers"],
            stdout = subprocess.PIPE,
            stderr = subprocess.DEVNULL,
            text = True,
            encoding = "utf-8",
            errors = "replace",
            timeout = 15,
            **kwargs
        )

    except (OSError, subprocess.SubprocessError):
        logger.warning("探测 FFmpeg 封装器失败，将退回按扩展名推断容器", exc_info = True)

        return set()

    muxers = {
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := _MUXER_PATTERN.match(line))
    }

    logger.info("FFmpeg 支持的封装器：%s", ", ".join(sorted(muxers)))

    return muxers


def supports_muxer(name: str) -> bool:
    """判断当前 FFmpeg 是否有指定封装器；探测不到时按支持处理，交给 FFmpeg 自己报错"""
    if not runtime.ffmpeg.muxers:
        runtime.ffmpeg.muxers = probe_supported_muxers()

    if not runtime.ffmpeg.muxers:
        return True

    return name in runtime.ffmpeg.muxers

