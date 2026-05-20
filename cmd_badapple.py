#!/usr/bin/env python3
"""Play videos as high-contrast ASCII art in Windows CMD with optional audio."""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover - optional fallback helper
    imageio_ffmpeg = None


STD_OUTPUT_HANDLE = -11
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
DISABLE_NEWLINE_AUTO_RETURN = 0x0008


class _COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


def enable_vt_mode() -> bool:
    """Enable ANSI escape support for Windows console output."""
    if os.name != "nt":
        return True

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    if handle == 0:
        return False

    mode = ctypes.c_uint()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
        return False

    new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING | DISABLE_NEWLINE_AUTO_RETURN
    if kernel32.SetConsoleMode(handle, new_mode) == 0:
        new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(handle, new_mode))
    return True


def move_cursor_home_legacy() -> bool:
    """Move cursor to 0,0 using Win32 API when ANSI VT is unavailable."""
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    if handle == 0:
        return False
    coord = _COORD(0, 0)
    return bool(kernel32.SetConsoleCursorPosition(handle, coord))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Play a video in CMD as inverted ASCII art with optional synced audio."
    )
    parser.add_argument("--video", required=True, help="Path to local input video file (.mp4 recommended).")
    parser.add_argument(
        "--audio",
        default="auto",
        help="Path to audio file (.mp3/.wav) or 'auto' to extract from --video. Default: auto",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=0,
        help="Target character width. Use 0 to auto-fit terminal width. Default: 0",
    )
    parser.add_argument("--fps", type=float, default=0.0, help="Playback FPS (0 = use source FPS).")
    parser.add_argument(
        "--chars",
        default=" @%ux",
        help="ASCII ramp from bright to dark characters. Default: ' @%%ux'",
    )
    parser.add_argument(
        "--invert",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Invert mapping so subject tends to become empty and background gets characters. Default: true",
    )
    parser.add_argument("--no-audio", action="store_true", help="Disable audio playback.")
    return parser.parse_args()


def get_render_width(requested_width: int) -> int:
    cols = shutil.get_terminal_size((120, 40)).columns
    # Keep margin to avoid line-wrap at the right border in classic CMD.
    safe_cols = max(20, cols - 4)
    auto_cap = 160
    if requested_width <= 0:
        return min(safe_cols, auto_cap)
    return max(20, min(requested_width, safe_cols))


def select_ffmpeg() -> Optional[str]:
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    return None


def extract_audio_to_wav(video_path: Path, ffmpeg_bin: str) -> Optional[Path]:
    tmp_dir = Path(tempfile.mkdtemp(prefix="badapple_audio_"))
    wav_path = tmp_dir / "audio.wav"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(wav_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    return wav_path if wav_path.exists() else None


def build_frame(frame: np.ndarray, width: int, chars: str, invert: bool) -> list[str]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    aspect = h / max(1, w)
    target_h = max(1, int(width * aspect * 0.5))
    resized = cv2.resize(gray, (width, target_h), interpolation=cv2.INTER_AREA)

    # Keep character distribution high-contrast.
    normalized = resized.astype(np.float32) / 255.0
    gamma = 1.8
    normalized = np.power(normalized, gamma)
    if invert:
        normalized = 1.0 - normalized

    ramp = chars
    if len(ramp) < 2:
        ramp = " @%ux"

    # Expand default ramp so '@' appears more frequently in dark regions.
    if ramp == " @%ux":
        expanded = "   xu%@@@@@@@@@@"
    else:
        expanded = ramp

    idx = np.clip((normalized * (len(expanded) - 1)).astype(np.int32), 0, len(expanded) - 1)
    char_arr = np.array(list(expanded), dtype="<U1")
    mapped = char_arr[idx]
    return ["".join(row) for row in mapped]


def main() -> int:
    args = parse_args()
    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        print(f"[ERRO] Video nao encontrado: {video_path}")
        return 1

    if args.width < 0:
        print("[ERRO] --width precisa ser >= 0.")
        return 1

    vt_enabled = enable_vt_mode()
    if not vt_enabled:
        print("[WARN] ANSI VT indisponivel. Usando fallback para CMD classico.")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[ERRO] Nao foi possivel abrir o video: {video_path}")
        return 1

    source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    target_fps = args.fps if args.fps > 0 else source_fps
    target_fps = max(1.0, min(target_fps, 120.0))
    frame_period = 1.0 / target_fps

    ffmpeg_bin = select_ffmpeg()
    audio_temp: Optional[Path] = None
    audio_path: Optional[Path] = None

    if not args.no_audio:
        if args.audio.lower() == "auto":
            if ffmpeg_bin is not None:
                audio_temp = extract_audio_to_wav(video_path, ffmpeg_bin)
                audio_path = audio_temp
                if audio_path is None:
                    print("[WARN] Nao foi possivel extrair audio do video. Seguindo sem audio.")
            else:
                print("[WARN] ffmpeg nao encontrado para --audio auto. Seguindo sem audio.")
        else:
            candidate = Path(args.audio).expanduser().resolve()
            if candidate.exists():
                audio_path = candidate
            else:
                print(f"[WARN] Arquivo de audio nao encontrado, seguindo sem audio: {candidate}")

    audio_started = False
    if audio_path is not None:
        try:
            pygame.mixer.init(frequency=44100)
            pygame.mixer.music.load(str(audio_path))
            pygame.mixer.music.play()
            audio_started = True
        except Exception as exc:
            print(f"[WARN] Nao foi possivel iniciar audio ({exc}). Seguindo sem audio.")

    actual_width = get_render_width(args.width)
    buffered_frames = 0
    dropped_frames = 0
    prev_draw_h = 0
    prev_draw_w = actual_width
    start = time.perf_counter()

    if vt_enabled:
        # Hide cursor and disable auto-wrap to reduce glitches near right edge.
        sys.stdout.write("\x1b[2J\x1b[H\x1b[?25l\x1b[?7l")
        sys.stdout.flush()
    else:
        os.system("cls")

    try:
        while True:
            expected_time = start + buffered_frames * frame_period
            now = time.perf_counter()

            # Skip frames if we're behind to keep A/V synchronization.
            while now - expected_time > frame_period:
                if not cap.grab():
                    raise StopIteration
                dropped_frames += 1
                buffered_frames += 1
                expected_time = start + buffered_frames * frame_period

            ok, frame = cap.read()
            if not ok:
                break

            actual_width = get_render_width(args.width)
            lines = build_frame(frame, actual_width, args.chars, args.invert)
            draw_h = len(lines)
            draw_w = max((len(x) for x in lines), default=0)
            target_w = max(prev_draw_w, draw_w)

            padded_lines = [line.ljust(target_w) for line in lines]
            if prev_draw_h > draw_h:
                padded_lines.extend(" " * target_w for _ in range(prev_draw_h - draw_h))

            if vt_enabled:
                sys.stdout.write("\x1b[H")
            else:
                # Classic CMD fallback: force clear to avoid frame stacking glitches.
                os.system("cls")
                move_cursor_home_legacy()
            sys.stdout.write("\n".join(padded_lines))
            sys.stdout.flush()
            prev_draw_h = max(prev_draw_h, draw_h)
            prev_draw_w = target_w

            buffered_frames += 1
            sleep_for = expected_time + frame_period - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        pass
    except StopIteration:
        pass
    finally:
        if vt_enabled:
            sys.stdout.write("\x1b[0m\x1b[?7h\x1b[?25h\n")
        else:
            sys.stdout.write("\n")
        sys.stdout.flush()
        cap.release()
        if audio_started:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        if audio_temp is not None:
            try:
                audio_temp.unlink(missing_ok=True)
                audio_temp.parent.rmdir()
            except Exception:
                pass

    print(f"Frames renderizados: {buffered_frames} | Frames pulados: {dropped_frames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
