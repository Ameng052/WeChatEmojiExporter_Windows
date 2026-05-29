from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

MIN_RATIO = 0.6


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_standard(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"BM"):
        return "bmp"
    return None


def find_partitions(data: bytes) -> list[dict]:
    if len(data) < 16 or not data.startswith(b"wxgf"):
        raise ValueError("not wxgf")
    header_len = data[4]
    if header_len >= len(data):
        raise ValueError("invalid wxgf header length")
    for pat in (b"\x00\x00\x00\x01", b"\x00\x00\x01"):
        ret = []
        offset = 0
        while header_len + offset <= len(data):
            idx = data.find(pat, header_len + offset)
            if idx < 0:
                break
            if idx < 4:
                offset = idx - header_len + 1
                continue
            length = int.from_bytes(data[idx - 4:idx], "big")
            if length > 0 and idx + length <= len(data):
                ret.append({"offset": idx, "size": length, "ratio": length / len(data)})
                offset = idx - header_len + length
            else:
                offset = idx - header_len + 1
        if ret:
            return ret
    raise ValueError("no h265 partition found")


def _run_ffmpeg(ffmpeg: Path, input_h265: Path, output: Path, gif: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if gif:
        cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "hevc", "-i", str(input_h265), "-vf", "fps=12,scale=iw:ih:flags=lanczos", str(output)]
    else:
        cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "hevc", "-i", str(input_h265), "-frames:v", "1", str(output)]
    kwargs = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    # ffmpeg is a console executable; without these flags Windows pops a black terminal
    # for every conversion. Keep it fully background/GUI-friendly.
    if sys.platform.startswith("win"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    p = subprocess.run(cmd, **kwargs)
    if p.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        raise RuntimeError((p.stderr or p.stdout or "ffmpeg failed").strip())


def wxgf_to_standard(src: Path, out_dir: Path, name_prefix: str, ffmpeg_path: str | None = None) -> dict:
    data = src.read_bytes()
    direct = detect_standard(data)
    if direct:
        digest = sha256_bytes(data)
        out = out_dir / f"{name_prefix}_{digest[:8]}.{direct}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return {"ok": True, "source": str(src), "output": str(out), "type": direct, "sha256": digest, "size": out.stat().st_size, "converter": "direct"}

    parts = find_partitions(data)
    digest = sha256_bytes(data)
    stream = b"".join(data[p["offset"]:p["offset"] + p["size"]] for p in parts)
    max_part = max(parts, key=lambda p: p["ratio"])
    like_anime = len(parts) > 1 and max_part["ratio"] < MIN_RATIO
    if ffmpeg_path:
        ffmpeg = Path(ffmpeg_path)
    elif getattr(sys, "frozen", False):
        ffmpeg = Path(sys._MEIPASS) / "tools" / "ffmpeg" / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffmpeg.exe"
        if not ffmpeg.exists():
            ffmpeg = Path(sys.executable).resolve().parent / "_internal" / "tools" / "ffmpeg" / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffmpeg.exe"
    else:
        root = Path(__file__).resolve().parents[1]
        candidates = [
            root / "release_assets" / "ffmpeg.exe",
            root / "third_party" / "ffmpeg" / "ffmpeg.exe",
            Path(__file__).resolve().parents[2] / "tools" / "ffmpeg" / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffmpeg.exe",
        ]
        ffmpeg = next((p for p in candidates if p.exists()), Path(shutil.which("ffmpeg") or candidates[0]))
    if not ffmpeg.exists():
        raise FileNotFoundError(f"找不到 ffmpeg：{ffmpeg}")
    with tempfile.TemporaryDirectory() as td:
        h265 = Path(td) / "stream.h265"
        h265.write_bytes(stream)
        if like_anime:
            out = out_dir / f"{name_prefix}_{digest[:8]}.gif"
            try:
                _run_ffmpeg(ffmpeg, h265, out, gif=True)
                return {"ok": True, "source": str(src), "output": str(out), "type": "gif", "sha256": digest, "size": out.stat().st_size, "parts": len(parts), "converter": "ffmpeg_gif"}
            except Exception:
                # Fall back to a first-frame PNG if gif muxing fails.
                out = out_dir / f"{name_prefix}_{digest[:8]}.png"
                _run_ffmpeg(ffmpeg, h265, out, gif=False)
                return {"ok": True, "source": str(src), "output": str(out), "type": "png", "sha256": digest, "size": out.stat().st_size, "parts": len(parts), "converter": "ffmpeg_png_fallback"}
        else:
            out = out_dir / f"{name_prefix}_{digest[:8]}.png"
            _run_ffmpeg(ffmpeg, h265, out, gif=False)
            return {"ok": True, "source": str(src), "output": str(out), "type": "png", "sha256": digest, "size": out.stat().st_size, "parts": len(parts), "converter": "ffmpeg_png"}
