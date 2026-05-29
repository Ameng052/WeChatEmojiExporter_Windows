from __future__ import annotations

import ctypes
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


def list_processes() -> list[tuple[int, str]]:
    """Return [(pid, exe_name)] using Win32 ToolHelp; no shell/console window."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        out: list[tuple[int, str]] = []
        while ok:
            out.append((int(entry.th32ProcessID), str(entry.szExeFile)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return out
    finally:
        kernel32.CloseHandle(snapshot)


def find_wechat_pids() -> list[int]:
    names = {"wechat.exe", "weixin.exe"}
    pids = [pid for pid, name in list_processes() if name.lower() in names]
    # If multiple helper/old processes exist, the highest PID is usually the newest main process.
    return sorted(set(pids), reverse=True)


def detect_wechat_pid() -> int:
    pids = find_wechat_pids()
    return pids[0] if pids else 0


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def get_process_image_path(pid: int) -> str | None:
    """Return full executable path for a process when permitted."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        if ok:
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def find_wechat_processes() -> list[dict]:
    names = {"wechat.exe", "weixin.exe"}
    out = []
    for pid, name in list_processes():
        if name.lower() in names:
            out.append({"pid": pid, "name": name, "path": get_process_image_path(pid)})
    return sorted(out, key=lambda x: x["pid"], reverse=True)
