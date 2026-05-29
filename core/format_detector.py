from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

READ_HEAD = 512 * 1024


@dataclass(frozen=True)
class FormatInfo:
    kind: str          # png/jpg/gif/webp/bmp/apng/wxgf/v1mmwx/unknown
    ext: str           # output extension without dot
    mime: str
    supported: bool
    animated: bool = False
    note: str = ""


def _is_apng(data: bytes) -> bool:
    # APNG is normal PNG plus acTL chunk. Scan head; acTL appears before first IDAT.
    return data.startswith(b"\x89PNG\r\n\x1a\n") and b"acTL" in data[:READ_HEAD]


def detect_bytes(data: bytes, suffix: str = "") -> FormatInfo:
    suffix = suffix.lower().lstrip(".")
    if data.startswith(b"V1MMWX"):
        return FormatInfo("v1mmwx", "v1mmwx", "application/octet-stream", False, False,
                          "微信 3.9.x V1MMWX 本地封装：可在用户已登录且版本受支持时本地转换。")
    if data.startswith(b"wxgf"):
        return FormatInfo("wxgf", "wxgf", "application/octet-stream", False, True,
                          "微信 WXGF 内部图片/动图容器：可转换为 PNG/GIF，不改写原文件。")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if _is_apng(data):
            return FormatInfo("apng", "png", "image/apng", True, True)
        return FormatInfo("png", "png", "image/png", True, False)
    if data.startswith(b"\xff\xd8\xff"):
        return FormatInfo("jpg", "jpg", "image/jpeg", True, False)
    if data.startswith((b"GIF87a", b"GIF89a")):
        return FormatInfo("gif", "gif", "image/gif", True, True)
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        animated = b"ANIM" in data[:READ_HEAD]
        return FormatInfo("webp", "webp", "image/webp", True, animated)
    if data.startswith(b"BM"):
        return FormatInfo("bmp", "bmp", "image/bmp", True, False)

    if suffix in {"png", "jpg", "jpeg", "gif", "webp", "bmp"}:
        return FormatInfo("unknown", "bin", "application/octet-stream", False, False,
                          f"扩展名为 .{suffix}，但文件头未命中标准图片魔数，可能损坏或不是图片。")
    return FormatInfo("unknown", "bin", "application/octet-stream", False, False, "无法识别图片格式。")


def detect_file(path: Path) -> FormatInfo:
    with path.open("rb") as f:
        data = f.read(READ_HEAD)
    return detect_bytes(data, path.suffix)
