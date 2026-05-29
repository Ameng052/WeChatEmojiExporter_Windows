from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
from typing import Iterable, Iterator


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.0f} {u}" if u == "B" else f"{v:.1f} {u}"
        v /= 1024
    return f"{n} B"


def safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return path.name


def iter_files(root: Path) -> Iterator[Path]:
    # os.scandir recursion is faster and handles Windows paths well.
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            yield Path(e.path)
                    except OSError:
                        continue
        except OSError:
            continue


def candidate_custom_emotion_dirs(selected: Path) -> list[Path]:
    """Return only WeChat custom-emoji directories.

    Important: never fall back to scanning the selected directory itself.
    Users often pick ``...\wxid_xxx\FileStorage``; scanning that whole tree
    would export chat/download/temp pictures, not custom emojis.
    """
    selected = selected.resolve()
    candidates: list[Path] = []

    def add(p: Path):
        try:
            p = p.resolve()
        except Exception:
            pass
        if p.exists() and p.is_dir() and p.name.lower() == "customemotion" and p not in candidates:
            candidates.append(p)

    name = selected.name.lower()

    def add_from_wechat_files_root(root: Path):
        """Add CustomEmotion dirs below a WeChat Files root."""
        try:
            for child in root.iterdir():
                if child.is_dir():
                    add(child / "FileStorage" / "CustomEmotion")
        except OSError:
            pass

    def add_from_anchor(anchor: Path):
        # Exact directory:
        #   ...\FileStorage\CustomEmotion
        if anchor.name.lower() == "customemotion":
            add(anchor)

        # FileStorage directory or a child under FileStorage:
        #   ...\wxid_xxx\FileStorage
        #   ...\wxid_xxx\FileStorage\Temp
        if anchor.name.lower() == "filestorage":
            add(anchor / "CustomEmotion")
        if anchor.parent.name.lower() == "filestorage":
            add(anchor.parent / "CustomEmotion")

        # Account root:
        #   ...\WeChat Files\wxid_xxx
        add(anchor / "FileStorage" / "CustomEmotion")

        # Parent of WeChat Files or WeChat Files root:
        #   ...\WeChat Files
        #   D:\微信下载的文件
        if anchor.name.lower() == "wechat files":
            add_from_wechat_files_root(anchor)
        add_from_wechat_files_root(anchor / "WeChat Files")

    # Try the selected path and its nearby parents. This allows users to pick
    # FileStorage\Temp, a wxid_xxx subfolder, or the parent folder containing
    # "WeChat Files" while still only returning CustomEmotion directories.
    cur = selected
    for _ in range(8):
        add_from_anchor(cur)
        if cur.parent == cur:
            break
        cur = cur.parent

    return candidates


def _home_candidates() -> list[Path]:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    out = [
        home / "Documents" / "WeChat Files",
        home / "My Documents" / "WeChat Files",
        home / "OneDrive" / "Documents" / "WeChat Files",
        home / "Desktop" / "WeChat Files",
        home / "Downloads" / "WeChat Files",
        Path(os.environ.get("APPDATA", "")) / "Tencent" / "WeChat" / "WeChat Files",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Tencent" / "WeChat" / "WeChat Files",
    ]
    return [p for p in out if str(p)]


def _drive_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                roots.append(Path(f"{chr(65 + i)}:\\"))
    else:
        roots.append(Path("/"))
    return roots


def _find_wechat_files_dirs_bounded(root: Path, max_depth: int = 3, max_dirs: int = 8000) -> Iterator[Path]:
    """Bounded directory search for folders named 'WeChat Files'.

    It scans directories only, with shallow depth and hard limits to avoid
    walking arbitrary image trees.
    """
    skip = {
        "$recycle.bin", "system volume information", "windows", "program files",
        "program files (x86)", "programdata", "appdata", ".venv", "node_modules",
        "__pycache__", "build", "dist",
    }
    seen = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and seen < max_dirs:
        cur, depth = stack.pop()
        seen += 1
        try:
            name = cur.name.lower()
        except Exception:
            name = ""
        if name == "wechat files":
            yield cur
            # Account roots are below this folder; no need to search deeper here.
            continue
        if depth >= max_depth or name in skip:
            continue
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append((Path(e.path), depth + 1))
                    except OSError:
                        continue
        except OSError:
            continue


def autodetect_custom_emotion_dirs(hint: Path | None = None, max_results: int = 20) -> list[Path]:
    """Automatically locate WeChat CustomEmotion directories.

    The function first uses a user hint and common WeChat locations, then does a
    shallow bounded search for "WeChat Files" on local drive roots.
    """
    out: list[Path] = []

    def merge(paths: Iterable[Path]):
        for p in paths:
            try:
                p = p.resolve()
            except Exception:
                pass
            if p not in out:
                out.append(p)

    if hint:
        merge(candidate_custom_emotion_dirs(hint))
    for base in _home_candidates():
        merge(candidate_custom_emotion_dirs(base))
        if len(out) >= max_results:
            return out[:max_results]

    # Also test common non-system drive locations quickly.
    for drive in _drive_roots():
        for wf in _find_wechat_files_dirs_bounded(drive):
            merge(candidate_custom_emotion_dirs(wf))
            if len(out) >= max_results:
                return out[:max_results]
    return out[:max_results]
