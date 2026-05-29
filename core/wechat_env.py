from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from ctypes import wintypes

from .process_utils import find_wechat_processes

MAX_SUPPORTED = (3, 9, 12)
RESOURCE_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _first_existing(paths: list[Path]) -> Path:
    for p in paths:
        if p.exists():
            return p
    return paths[0]


if getattr(sys, "frozen", False):
    WECHAT_SETUP_PATH = RESOURCE_BASE / "WeChatSetup.exe"
else:
    WECHAT_SETUP_PATH = _first_existing([
        PROJECT_ROOT / "release_assets" / "WeChatSetup.exe",
        PROJECT_ROOT / "third_party" / "WeChatSetup.exe",
        PROJECT_ROOT / "WeChatSetup.exe",
    ])


@dataclass
class WeChatEnv:
    exe_path: str | None = None
    version: str | None = None
    compatible: bool = False
    running: bool = False
    pid: int = 0
    source: str = "none"
    message: str = ""


def parse_version(version: str | None) -> tuple[int, ...]:
    if not version:
        return tuple()
    nums = [int(x) for x in re.findall(r"\d+", version)[:4]]
    return tuple(nums)


def is_compatible_version(version: str | None) -> bool:
    nums = parse_version(version)
    if not nums:
        return False
    return nums[:3] <= MAX_SUPPORTED


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


def get_file_version(path: str | Path) -> str | None:
    path = str(path)
    version = ctypes.WinDLL("version", use_last_error=True)
    dummy = wintypes.DWORD(0)
    size = version.GetFileVersionInfoSizeW(path, ctypes.byref(dummy))
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, data):
        return None
    ptr = ctypes.c_void_p()
    length = wintypes.UINT(0)
    if not version.VerQueryValueW(data, "\\", ctypes.byref(ptr), ctypes.byref(length)):
        return None
    info = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    nums = [
        info.dwFileVersionMS >> 16,
        info.dwFileVersionMS & 0xFFFF,
        info.dwFileVersionLS >> 16,
        info.dwFileVersionLS & 0xFFFF,
    ]
    return ".".join(str(x) for x in nums)


def _clean_icon_path(value: str | None) -> Path | None:
    if not value:
        return None
    v = value.strip().strip('"')
    if "," in v:
        v = v.split(",", 1)[0].strip().strip('"')
    p = Path(os.path.expandvars(v))
    if p.name.lower() == "wechat.exe" and p.exists():
        return p
    return None


def _registry_candidates() -> list[Path]:
    out: list[Path] = []
    try:
        import winreg
    except Exception:
        return out
    roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
    subkeys = [
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    for root in roots:
        for sub in subkeys:
            try:
                key = winreg.OpenKey(root, sub)
            except OSError:
                continue
            try:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        sk_name = winreg.EnumKey(key, i)
                        sk = winreg.OpenKey(key, sk_name)
                        vals = {}
                        for j in range(winreg.QueryInfoKey(sk)[1]):
                            name, val, _ = winreg.EnumValue(sk, j)
                            vals[name] = val
                        display = str(vals.get("DisplayName", ""))
                        if "WeChat" not in display and "\u5fae\u4fe1" not in display:
                            continue
                        loc = vals.get("InstallLocation")
                        if loc:
                            exe = Path(os.path.expandvars(str(loc))) / "WeChat.exe"
                            if exe.exists():
                                out.append(exe)
                        icon = _clean_icon_path(str(vals.get("DisplayIcon", "")))
                        if icon:
                            out.append(icon)
                    except OSError:
                        continue
            finally:
                try:
                    winreg.CloseKey(key)
                except Exception:
                    pass
    return out


def _common_candidates() -> list[Path]:
    bases = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LocalAppData"),
        r"D:\Program Files (x86)",
        r"D:\Program Files",
    ]
    rels = [
        r"Tencent\WeChat\WeChat.exe",
        r"WeChat\WeChat.exe",
    ]
    out = []
    for b in bases:
        if not b:
            continue
        for rel in rels:
            p = Path(b) / rel
            if p.exists():
                out.append(p)
    return out


def find_wechat_exe_in_dir(directory: str | Path) -> Path | None:
    d = Path(directory)
    if d.is_file() and d.name.lower() == "wechat.exe":
        return d
    direct = d / "WeChat.exe"
    if direct.exists():
        return direct
    try:
        hits = list(d.rglob("WeChat.exe"))
        return hits[0] if hits else None
    except Exception:
        return None


def detect_wechat_environment(preferred_dir: str | None = None) -> WeChatEnv:
    # 1) Running process has priority: it is the instance Frida will attach to.
    running = find_wechat_processes()
    if running:
        detected = []
        for proc in running:
            exe = proc.get("path")
            ver = get_file_version(exe) if exe else None
            detected.append(WeChatEnv(exe, ver, is_compatible_version(ver), True, int(proc["pid"]), "process"))
        # Prefer a compatible running instance if several processes/old instances exist.
        compatible = [x for x in detected if x.compatible]
        return compatible[0] if compatible else detected[0]

    candidates: list[Path] = []
    if preferred_dir:
        found = find_wechat_exe_in_dir(preferred_dir)
        if found:
            candidates.append(found)
    candidates.extend(_registry_candidates())
    candidates.extend(_common_candidates())

    seen = set()
    for exe in candidates:
        key = str(exe).lower()
        if key in seen:
            continue
        seen.add(key)
        if exe.exists():
            ver = get_file_version(exe)
            return WeChatEnv(str(exe), ver, is_compatible_version(ver), False, 0, "install")
    return WeChatEnv(message="not_found")


def start_wechat(exe_path: str | Path) -> None:
    exe = Path(exe_path)
    kwargs = {"cwd": str(exe.parent), "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe)], **kwargs)


def start_installer() -> None:
    if not WECHAT_SETUP_PATH.exists():
        raise FileNotFoundError(str(WECHAT_SETUP_PATH))
    subprocess.Popen([str(WECHAT_SETUP_PATH)], cwd=str(WECHAT_SETUP_PATH.parent), close_fds=True)
