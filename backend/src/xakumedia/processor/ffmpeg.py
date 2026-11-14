"""FFmpeg and FFprobe binary detection, stream multiplexing, and format conversion."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.config import default_config
from ..core.logging import get_logger
from ..exceptions.base import (
    DownloadCancelledError,
    FFmpegNotFoundError,
    FormatConversionError,
    StreamMergeError,
)

logger = get_logger("processor.ffmpeg")


def find_ffmpeg() -> Path | None:
    """Locate the FFmpeg executable dynamically from config, PATH, or standard paths."""
    # 0. Environment variable override
    env_ffmpeg = os.environ.get("FFMPEG_PATH")
    if env_ffmpeg and Path(env_ffmpeg).is_file():
        return Path(env_ffmpeg)

    # 1. Configured custom path
    if default_config.ffmpeg_binary and default_config.ffmpeg_binary.exists():
        return default_config.ffmpeg_binary

    # 2. Packaged relative resource locations (resources/bin/ffmpeg.exe)
    packaged_candidates = [
        Path(sys.executable).parent.parent / "bin" / "ffmpeg.exe",
        Path(sys.executable).parent / "bin" / "ffmpeg.exe",
        Path(__file__).resolve().parents[4] / "bin" / "ffmpeg.exe",
    ]
    for candidate in packaged_candidates:
        if candidate.is_file():
            return candidate

    # 3. System PATH lookup
    system_bin = shutil.which("ffmpeg")
    if system_bin:
        return Path(system_bin)

    # 4. Windows common installation locations
    if os.name == "nt":
        local_app = Path(os.environ.get("LOCALAPPDATA", ""))
        prog_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
        candidates = [
            Path("C:\\lib\\ffmpeg-n4.4-latest-win64-gpl-4.4\\bin\\ffmpeg.exe"),
            local_app / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe",
            prog_files / "FFmpeg" / "bin" / "ffmpeg.exe",
            Path("C:\\ffmpeg\\bin\\ffmpeg.exe"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate

    return None


def find_ffprobe() -> Path | None:
    """Locate the FFprobe executable dynamically from config, PATH, or standard paths."""
    # 0. Environment variable override
    env_ffprobe = os.environ.get("FFPROBE_PATH")
    if env_ffprobe and Path(env_ffprobe).is_file():
        return Path(env_ffprobe)

    if default_config.ffprobe_binary and default_config.ffprobe_binary.exists():
        return default_config.ffprobe_binary

    packaged_candidates = [
        Path(sys.executable).parent.parent / "bin" / "ffprobe.exe",
        Path(sys.executable).parent / "bin" / "ffprobe.exe",
        Path(__file__).resolve().parents[4] / "bin" / "ffprobe.exe",
    ]
    for candidate in packaged_candidates:
        if candidate.is_file():
            return candidate

    system_bin = shutil.which("ffprobe")
    if system_bin:
        return Path(system_bin)

    if os.name == "nt":
        local_app = Path(os.environ.get("LOCALAPPDATA", ""))
        prog_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
        candidates = [
            Path("C:\\lib\\ffmpeg-n4.4-latest-win64-gpl-4.4\\bin\\ffprobe.exe"),
            local_app / "Microsoft" / "WinGet" / "Links" / "ffprobe.exe",
            prog_files / "FFmpeg" / "bin" / "ffprobe.exe",
            Path("C:\\ffmpeg\\bin\\ffprobe.exe"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate

    return None


def get_ffmpeg_version(ffmpeg_path: Path | None = None) -> str | None:
    """Query and parse the version string of the installed FFmpeg binary."""
    binary = ffmpeg_path or find_ffmpeg()
    if not binary:
        return None

    try:
        proc = subprocess.run(
            [str(binary), "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
        if proc.returncode == 0 and proc.stdout:
            first_line = proc.stdout.splitlines()[0]
            match = re.search(r"ffmpeg version\s+([^\s]+)", first_line, re.IGNORECASE)
            if match:
                return match.group(1)
            return first_line.strip()
    except Exception as exc:
        logger.warning(f"Failed to query FFmpeg version from {binary}: {exc}")

    return None


def get_ffmpeg_info() -> dict[str, Any]:
    """Retrieve system diagnostics regarding FFmpeg and FFprobe availability."""
    ffmpeg_bin = find_ffmpeg()
    ffprobe_bin = find_ffprobe()
    version = get_ffmpeg_version(ffmpeg_bin) if ffmpeg_bin else None

    return {
        "installed": ffmpeg_bin is not None,
        "version": version,
        "ffmpeg_path": str(ffmpeg_bin) if ffmpeg_bin else None,
        "ffprobe_path": str(ffprobe_bin) if ffprobe_bin else None,
    }


# Container extension -> FFmpeg muxer. Staging files such as ``name.mp4.part``
# have an extension that FFmpeg cannot map, so callers must pass the real
# container and the command must name the muxer explicitly with ``-f``.
_CONTAINER_MUXERS = {
    "mp4": "mp4",
    "m4v": "mp4",
    "mov": "mov",
    "mkv": "matroska",
    "mka": "matroska",
    "webm": "webm",
    "ts": "mpegts",
    "avi": "avi",
    "flv": "flv",
}


def muxer_for_container(container: str | None) -> str:
    """Map a file extension/container name to an explicit FFmpeg muxer."""
    key = (container or "").lower().lstrip(".")
    if key in _CONTAINER_MUXERS:
        return _CONTAINER_MUXERS[key]
    # Unknown or staging extensions (``part``/``tmp``) are safest in Matroska.
    return "matroska"


def _probe_stream_codecs(
    file_path: Path, ffprobe_path: Path | None = None
) -> tuple[str | None, str | None]:
    """Return the first video and audio codec names, or ``(None, None)``."""
    probe_bin = ffprobe_path or find_ffprobe()
    if not probe_bin:
        return None, None
    try:
        proc = subprocess.run(
            [
                str(probe_bin),
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20.0,
        )
        data = json.loads(proc.stdout or "{}")
    except Exception as exc:  # probing is best-effort; merge still attempts copy
        logger.debug(f"Could not probe codecs for {file_path.name}: {exc}")
        return None, None

    video_codec: str | None = None
    audio_codec: str | None = None
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and video_codec is None:
            video_codec = stream.get("codec_name")
        elif codec_type == "audio" and audio_codec is None:
            audio_codec = stream.get("codec_name")
    return video_codec, audio_codec


def _terminate_process(proc: subprocess.Popen) -> None:
    """Terminate a child process and guarantee it is reaped."""
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
        return
    except subprocess.TimeoutExpired:
        proc.kill()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        logger.warning("FFmpeg process did not exit after kill signal")


def _run_ffmpeg_command(
    args: list[str],
    *,
    output_path: Path,
    is_cancelled: Callable[[], bool] | None = None,
    timeout_seconds: float = 600.0,
    operation: str = "FFmpeg operation",
) -> tuple[int, str]:
    """Run FFmpeg with drained stderr, cancellation, timeout, and no deadlocks.

    stderr is written to an anonymous temp file instead of a pipe: FFmpeg emits
    progress continuously and a full pipe would block the process forever when
    the parent is not reading it.
    """
    with tempfile.TemporaryFile(
        mode="w+", encoding="utf-8", errors="replace"
    ) as err_file:
        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err_file,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise FFmpegNotFoundError(f"Could not start FFmpeg: {exc}") from exc

        started = time.monotonic()
        try:
            while True:
                if is_cancelled and is_cancelled():
                    _terminate_process(proc)
                    logger.warning(f"Cancellation received during {operation}")
                    if output_path.exists():
                        try:
                            output_path.unlink()
                        except OSError:
                            pass
                    raise DownloadCancelledError(f"{operation} cancelled by user")

                if time.monotonic() - started > timeout_seconds:
                    _terminate_process(proc)
                    if output_path.exists():
                        try:
                            output_path.unlink()
                        except OSError:
                            pass
                    raise StreamMergeError(
                        f"{operation} timed out after {int(timeout_seconds)}s"
                    )

                try:
                    returncode = proc.wait(timeout=0.15)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if proc.poll() is None:
                _terminate_process(proc)

        err_file.seek(0)
        stderr_text = err_file.read().strip()
    return returncode, stderr_text


def inspect_media(file_path: Path, ffprobe_path: Path | None = None) -> dict[str, Any]:
    """Inspect media container, duration, format, and stream tracks via FFprobe.

    Returns:
        Structured dictionary containing container format details and stream tracks.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Media file not found for inspection: {file_path}")

    probe_bin = ffprobe_path or find_ffprobe()
    if not probe_bin:
        raise FFmpegNotFoundError("ffprobe executable was not found on system PATH.")

    cmd = [
        str(probe_bin),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=15.0,
        )
        if proc.returncode != 0:
            raise StreamMergeError(
                f"ffprobe failed to inspect {file_path.name}: {proc.stderr.strip()}"
            )

        data = json.loads(proc.stdout)
        format_info = data.get("format", {})
        streams = data.get("streams", [])

        video_tracks = [s for s in streams if s.get("codec_type") == "video"]
        audio_tracks = [s for s in streams if s.get("codec_type") == "audio"]

        return {
            "file_name": file_path.name,
            "format_name": format_info.get("format_name"),
            "duration_seconds": float(format_info.get("duration", 0.0)) or None,
            "size_bytes": int(format_info.get("size", 0)) or None,
            "bit_rate": int(format_info.get("bit_rate", 0)) or None,
            "video_stream": {
                "codec": video_tracks[0].get("codec_name"),
                "width": video_tracks[0].get("width"),
                "height": video_tracks[0].get("height"),
                "fps": eval(video_tracks[0].get("r_frame_rate", "0/1"))
                if "/" in video_tracks[0].get("r_frame_rate", "")
                else None,
            }
            if video_tracks
            else None,
            "audio_stream": {
                "codec": audio_tracks[0].get("codec_name"),
                "sample_rate": audio_tracks[0].get("sample_rate"),
                "channels": audio_tracks[0].get("channels"),
            }
            if audio_tracks
            else None,
            "stream_count": len(streams),
        }
    except json.JSONDecodeError as exc:
        raise StreamMergeError(f"Failed to parse ffprobe output: {exc}") from exc


def merge_video_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    output_container: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    ffmpeg_path: Path | None = None,
) -> Path:
    """Multiplex separate video and audio tracks into a single container without re-encoding.

    Args:
        video_path: Local path to the downloaded video-only stream file.
        audio_path: Local path to the downloaded audio-only stream file.
        output_path: Target destination path for the multiplexed media file.
        output_container: Optional explicit container extension (e.g. 'mp4', 'mkv').
        is_cancelled: Optional cancellation predicate polled during merge execution.
        ffmpeg_path: Optional explicit path to the FFmpeg binary.

    Returns:
        Path to the multiplexed file.
    """
    if not video_path.is_file():
        raise FileNotFoundError(f"Video stream file not found: {video_path}")
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio stream file not found: {audio_path}")

    bin_path = ffmpeg_path or find_ffmpeg()
    if not bin_path:
        raise FFmpegNotFoundError(
            "FFmpeg executable not found. Cannot multiplex separate video and audio streams."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    container = (output_container or output_path.suffix.lstrip(".")).lower()
    if container in ("", "part", "tmp"):
        # A staging filename (e.g. ``clip.mp4.part``) carries no usable
        # extension. Matroska accepts virtually every codec combination.
        container = "mkv"
    muxer = muxer_for_container(container)

    video_codec, _ = _probe_stream_codecs(video_path)
    _, audio_codec = _probe_stream_codecs(audio_path)
    logger.info(
        f"Merging streams: {video_path.name} ({video_codec or '?'}) + "
        f"{audio_path.name} ({audio_codec or '?'}) -> {output_path.name} [{muxer}]"
    )

    # Each attempt is a complete mux command. Copy first, then transcode only
    # what the container rejects: audio for MP4, everything for WebM when the
    # source video codec is not WebM-compatible.
    audio_transcode = (
        ["-c:a", "libopus", "-b:a", "160k"]
        if muxer == "webm"
        else ["-c:a", "aac", "-b:a", "192k"]
    )
    if muxer == "webm":
        video_transcode = [
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "32",
            "-b:v",
            "0",
            "-c:a",
            "libopus",
            "-b:a",
            "160k",
        ]
    else:
        video_transcode = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            *audio_transcode,
        ]

    attempts: list[tuple[str, list[str]]] = [
        ("lossless copy", ["-c:v", "copy", "-c:a", "copy"]),
        ("copy video + transcode audio", ["-c:v", "copy", *audio_transcode]),
        ("transcode video + audio", video_transcode),
    ]

    last_error = ""
    for index, (label, codec_args) in enumerate(attempts):
        # Attempting to stream-copy VP8/VP9 into MP4 or H.264 into WebM is a
        # guaranteed failure on older FFmpeg builds; skip straight to transcode.
        if index == 0 and muxer == "webm" and video_codec and video_codec not in {
            "vp8",
            "vp9",
            "av1",
        }:
            last_error = f"video codec {video_codec} is not WebM-compatible"
            continue
        if index == 0 and muxer in ("mp4", "mov") and video_codec in {
            "vp8",
            "theora",
            "wmv1",
            "wmv2",
            "wmv3",
            "msmpeg4v3",
        }:
            last_error = f"video codec {video_codec} is not MP4-compatible"
            continue

        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass

        cmd = [
            str(bin_path),
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            *codec_args,
        ]
        if container == "mp4":
            cmd.extend(["-movflags", "+faststart"])
        cmd.extend(["-f", muxer, str(output_path)])

        logger.info(f"Stream merge attempt {index + 1} ({label}) for {output_path.name}")
        try:
            returncode, stderr = _run_ffmpeg_command(
                cmd,
                output_path=output_path,
                is_cancelled=is_cancelled,
                operation="Stream merge",
            )
        except StreamMergeError:
            raise
        except DownloadCancelledError:
            raise
        except FFmpegNotFoundError:
            raise
        except Exception as exc:  # keep trying safer encodings
            last_error = str(exc)
            logger.warning(f"Stream merge attempt {index + 1} errored: {exc}")
            continue

        if returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0:
            # Never report success on a video-only file: verify both tracks.
            merged_video, merged_audio = _probe_stream_codecs(output_path)
            if merged_video and merged_audio:
                size_bytes = output_path.stat().st_size
                logger.info(
                    f"Stream merge completed successfully: {output_path} "
                    f"({size_bytes} bytes, {label})"
                )
                return output_path
            last_error = (
                "output is missing an audio or video stream "
                f"(video={merged_video or 'none'}, audio={merged_audio or 'none'})"
            )
            logger.warning(f"Merge attempt {index + 1} produced an incomplete file: {last_error}")

        last_error = stderr.strip()[-800:] if stderr.strip() else last_error
        logger.warning(f"Stream merge attempt {index + 1} failed: {last_error}")
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass

    raise StreamMergeError(
        "FFmpeg stream merge failed after all fallbacks"
        + (f": {last_error}" if last_error else ""),
        details={
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "container": container,
        },
    )


def convert_container(
    input_path: Path,
    output_path: Path,
    is_cancelled: Callable[[], bool] | None = None,
    ffmpeg_path: Path | None = None,
) -> Path:
    """Convert media container format using stream copy where possible."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Source media file not found: {input_path}")

    bin_path = ffmpeg_path or find_ffmpeg()
    if not bin_path:
        raise FFmpegNotFoundError("FFmpeg executable not found for format conversion.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    container = output_path.suffix.lstrip(".").lower()
    muxer = muxer_for_container(container)

    def build(codec_args: list[str]) -> list[str]:
        args = [
            str(bin_path),
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            *codec_args,
        ]
        if container == "mp4":
            args.extend(["-movflags", "+faststart"])
        args.extend(["-f", muxer, str(output_path)])
        return args

    transcode_args = (
        ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-c:a", "libopus", "-b:a", "160k"]
        if muxer == "webm"
        else [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
    )

    last_error = ""
    for index, codec_args in enumerate((["-c", "copy"], transcode_args)):
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        try:
            returncode, stderr = _run_ffmpeg_command(
                build(codec_args),
                output_path=output_path,
                is_cancelled=is_cancelled,
                operation="Container conversion",
            )
        except DownloadCancelledError:
            raise
        except FFmpegNotFoundError:
            raise
        except StreamMergeError as exc:
            raise FormatConversionError(exc.message, details=exc.details) from exc

        if returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0:
            return output_path
        last_error = stderr or f"attempt {index + 1} failed"
        logger.warning(f"Container conversion attempt {index + 1} failed: {last_error}")

    if output_path.exists():
        try:
            output_path.unlink()
        except OSError:
            pass
    raise FormatConversionError(f"FFmpeg container conversion failed: {last_error}")


def extract_audio(
    input_path: Path,
    output_path: Path,
    audio_format: str = "mp3",
    bitrate: str = "192k",
    is_cancelled: Callable[[], bool] | None = None,
    ffmpeg_path: Path | None = None,
) -> Path:
    """Extract audio track from video file and encode to MP3/M4A/WAV."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Source media file not found: {input_path}")

    bin_path = ffmpeg_path or find_ffmpeg()
    if not bin_path:
        raise FFmpegNotFoundError("FFmpeg executable not found for audio extraction.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio_format_lower = audio_format.lower()
    codec = "libmp3lame" if audio_format_lower == "mp3" else "aac"
    muxer = (
        "mp3"
        if audio_format_lower == "mp3"
        else "wav"
        if audio_format_lower == "wav"
        else "ipod"
        if audio_format_lower in ("m4a", "aac", "mp4")
        else "mp3"
    )
    cmd = [
        str(bin_path),
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        codec,
        "-b:a",
        bitrate,
        "-f",
        muxer,
        str(output_path),
    ]

    try:
        returncode, stderr = _run_ffmpeg_command(
            cmd,
            output_path=output_path,
            is_cancelled=is_cancelled,
            operation="Audio extraction",
        )
    except DownloadCancelledError:
        raise
    except StreamMergeError as exc:
        raise FormatConversionError(exc.message, details=exc.details) from exc

    if returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        raise FormatConversionError(f"Audio extraction failed: {stderr}")

    return output_path
