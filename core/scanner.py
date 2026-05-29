from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot

from .format_detector import detect_file
from .models import EmojiItem, ScanStats
from .utils import candidate_custom_emotion_dirs, iter_files, safe_rel, sha256_file
from .process_utils import get_process_image_path
from .v1mmwx_decoder import decode_v1mmwx_batch, get_decoder_rva_for_version, supported_decoder_versions
from .wechat_env import get_file_version
from .wxgf_converter import wxgf_to_standard


class ScanWorker(QObject):
    item_found = Signal(object)       # EmojiItem
    progress = Signal(int, int)       # scanned_files, recognized
    log = Signal(str)
    finished = Signal(object)         # ScanStats

    def __init__(self, selected_dir: str, decode_v1mmwx: bool = False, wechat_pid: int = 0, work_dir: str | None = None):
        super().__init__()
        self.selected_dir = Path(selected_dir)
        self.decode_v1mmwx = decode_v1mmwx
        self.wechat_pid = int(wechat_pid or 0)
        self.work_dir = Path(work_dir) if work_dir else Path.cwd() / "decoded_scan_cache"
        self._stop = False
        self._idx = 0

    @Slot()
    def stop(self):
        self._stop = True

    def _emit_standard_item(self, path: Path, root: Path, info=None, original_path: Path | None = None):
        info = info or detect_file(path)
        size = path.stat().st_size
        digest = sha256_file(path)
        self._idx += 1
        rel_target = original_path or path
        note = info.note
        if original_path:
            note = (note + "；" if note else "") + f"原始文件：{original_path}"
        item = EmojiItem(
            id=self._idx,
            source_path=str(path),
            rel_path=safe_rel(rel_target, root),
            file_type=info.kind.upper(),
            ext=info.ext,
            size=size,
            sha256=digest,
            scanned_at=datetime.now().isoformat(timespec="seconds"),
            original_path=str(original_path) if original_path else str(path),
            note=note,
        )
        self.item_found.emit(item)
        return item

    @staticmethod
    def _is_ascii_path(path: Path) -> bool:
        try:
            str(path).encode("ascii")
            return True
        except UnicodeEncodeError:
            return False

    def _fallback_ascii_work_dir(self) -> Path:
        candidates = []
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramData"), str(Path.cwd())):
            if base:
                candidates.append(Path(base) / "WeChatEmojiExporter" / "decode_cache")
        for cand in candidates:
            if self._is_ascii_path(cand):
                try:
                    cand.mkdir(parents=True, exist_ok=True)
                    return cand
                except Exception:
                    continue
        return self.work_dir

    def _work_root(self) -> Path:
        if self._is_ascii_path(self.work_dir):
            return self.work_dir
        fallback = self._fallback_ascii_work_dir()
        if fallback != self.work_dir:
            self.log.emit(f"中间目录包含非 ASCII 字符，已自动切换到：{fallback}")
        return fallback

    def _decoder_context(self) -> tuple[str, int] | None:
        exe = get_process_image_path(self.wechat_pid)
        ver = get_file_version(exe) if exe else None
        rva = get_decoder_rva_for_version(ver)
        if not rva:
            verified = ", ".join(supported_decoder_versions())
            self.log.emit(
                f"当前微信版本 {ver or '未知'} 未验证 V1MMWX 解码地址，已停止转换。"
                f"请使用已验证版本：{verified}。"
            )
            return None
        self.log.emit(f"已确认微信版本 {ver}，使用 V1MMWX 解码地址 0x{rva:x}。")
        return ver, rva

    def _convert_wxgf_file(self, wxgf: Path, emoji_dir: Path, root: Path, stats: ScanStats, original_path: Path | None = None, ordinal: int = 0):
        res = wxgf_to_standard(wxgf, emoji_dir, wxgf.stem)
        out = Path(res["output"])
        info = detect_file(out)
        self._emit_standard_item(out, root, info, original_path=original_path or wxgf)
        stats.recognized += 1
        label = original_path.name if original_path else wxgf.name
        if ordinal <= 10 or ordinal % 25 == 0:
            self.log.emit(f"转换成功：{label} -> {out.name}")
        return res

    def _convert_wxgf_files(self, files: list[tuple[Path, Path]], stats: ScanStats):
        if not files or self._stop:
            return
        cache = self._work_root() / datetime.now().strftime("wxgf_%Y%m%d_%H%M%S")
        emoji_dir = cache / "emojis"
        log_dir = cache / "logs"
        try:
            for d in (emoji_dir, log_dir):
                d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log.emit(f"创建 WXGF 中间目录失败：{cache}，原因：{e}")
            return
        results = []
        self.log.emit(f"开始 WXGF 转换：{len(files)} 个；中间目录：{cache}")
        for n, (wxgf, root) in enumerate(files, 1):
            if self._stop:
                break
            try:
                results.append(self._convert_wxgf_file(wxgf, emoji_dir, root, stats, original_path=wxgf, ordinal=n))
            except Exception as e:
                results.append({"ok": False, "source": str(wxgf), "error": str(e)})
                self.log.emit(f"WXGF 转图片失败：{wxgf}，原因：{e}")
            self.progress.emit(stats.scanned_files, stats.recognized)
        try:
            (log_dir / "wxgf_convert_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.log.emit(f"WXGF 转换日志写入失败：{e}")

    def _decode_v1mmwx_files(self, files: list[Path], root: Path, stats: ScanStats):
        if not files:
            return
        if not self.decode_v1mmwx:
            return
        if self.wechat_pid <= 0:
            self.log.emit("已发现 V1MMWX，但未填写微信 PID；不会转换。")
            return
        decoder = self._decoder_context()
        if not decoder:
            return
        wechat_version, decoder_rva = decoder
        cache = self._work_root() / datetime.now().strftime("decode_%Y%m%d_%H%M%S")
        raw_dir = cache / "raw_v1mmwx"
        wxgf_dir = cache / "wxgf"
        emoji_dir = cache / "emojis"
        log_dir = cache / "logs"
        try:
            for d in (raw_dir, wxgf_dir, emoji_dir, log_dir):
                d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log.emit(f"创建 V1MMWX 中间目录失败：{cache}，原因：{e}")
            return

        jobs = []
        mapping = []
        self.log.emit(f"开始 V1MMWX 解码：{len(files)} 个；中间目录：{cache}")
        for i, src in enumerate(files, 1):
            if self._stop:
                break
            try:
                digest = sha256_file(src)
                # Frida's in-process File API is not Unicode-path safe on some Windows builds.
                # Use an ASCII-only staging directory so Chinese WeChat paths decode reliably.
                raw = raw_dir / f"emoji_{i:04d}_{digest[:8]}.v1mmwx"
                shutil.copy2(src, raw)
                wxgf = wxgf_dir / f"emoji_{i:04d}_{digest[:8]}.wxgf"
                jobs.append({"input": str(raw), "output": str(wxgf)})
                mapping.append((src, raw, wxgf, digest))
            except Exception as e:
                stats.unreadable += 1
                self.log.emit(f"复制 V1MMWX 失败：{src}，原因：{e}")

        all_results = []
        convert_results = []
        batch_size = 40
        for start in range(0, len(jobs), batch_size):
            if self._stop:
                break
            try:
                batch_jobs = jobs[start:start + batch_size]
                batch_mapping = mapping[start:start + batch_size]
                results = decode_v1mmwx_batch(
                    self.wechat_pid,
                    batch_jobs,
                    timeout=max(120, len(batch_jobs) * 5),
                    wechat_version=wechat_version,
                    decoder_rva=decoder_rva,
                )
                all_results.extend(results)
            except Exception as e:
                self.log.emit(f"V1MMWX 解码失败：{e}")
                self.log.emit("提示：请确认微信 3.9.12.57 正在运行、PID 正确，并用管理员权限运行本工具/终端。")
                break

            ok_by_output = {r.get("output"): r for r in results if r.get("ok")}
            for offset, (orig, raw, wxgf, digest) in enumerate(batch_mapping, start + 1):
                if self._stop:
                    break
                if str(wxgf) not in ok_by_output:
                    self.log.emit(f"微信内部解码失败：{orig}")
                    continue
                try:
                    res = self._convert_wxgf_file(wxgf, emoji_dir, root, stats, original_path=orig, ordinal=offset)
                    convert_results.append(res)
                except Exception as e:
                    convert_results.append({"ok": False, "source": str(wxgf), "original": str(orig), "error": str(e)})
                    self.log.emit(f"WXGF 转图片失败：{orig}，原因：{e}")
                self.progress.emit(stats.scanned_files, stats.recognized)
            self.log.emit(f"V1MMWX 解码进度：{min(start + batch_size, len(jobs))}/{len(jobs)}")
        (log_dir / "frida_decode_results.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        (log_dir / "wxgf_convert_results.json").write_text(json.dumps(convert_results, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log.emit(f"V1MMWX 转换完成：识别图片 {stats.recognized} 个；最终图片目录：{emoji_dir}")

    @Slot()
    def run(self):
        stats = ScanStats()
        roots = candidate_custom_emotion_dirs(self.selected_dir)
        if not roots:
            self.log.emit(
                "未找到微信自定义表情目录 CustomEmotion。请确认选择的是："
                "WeChat Files、wxid_xxx、FileStorage 或 FileStorage\\CustomEmotion。"
            )
            self.progress.emit(0, 0)
            self.finished.emit(stats)
            return
        self.log.emit("扫描目录：" + "；".join(str(p) for p in roots))
        seen_paths = set()
        v1_files: list[tuple[Path, Path]] = []
        wxgf_files: list[tuple[Path, Path]] = []
        for root in roots:
            if self._stop:
                break
            for path in iter_files(root):
                if self._stop:
                    self.log.emit("用户停止扫描。")
                    break
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                stats.scanned_files += 1
                try:
                    info = detect_file(path)
                    if not info.supported:
                        if info.kind == "v1mmwx":
                            stats.encrypted_v1mmwx += 1
                            v1_files.append((path, root))
                        elif info.kind == "wxgf":
                            stats.wxgf += 1
                            wxgf_files.append((path, root))
                        else:
                            stats.unsupported += 1
                        if stats.scanned_files % 200 == 0:
                            self.progress.emit(stats.scanned_files, stats.recognized)
                        continue
                    self._emit_standard_item(path, root, info)
                    stats.recognized += 1
                    if self._idx <= 10 or self._idx % 50 == 0:
                        self.log.emit(f"识别成功：{info.kind.upper()}  {path}")
                except Exception as e:
                    stats.unreadable += 1
                    self.log.emit(f"读取失败：{path}，原因：{e}")
                if stats.scanned_files % 50 == 0:
                    self.progress.emit(stats.scanned_files, stats.recognized)

        # Decode V1MMWX after passive scan; all decoded outputs are safe copies under work_dir.
        if v1_files and not self._stop:
            # Use the first matching root for relative display; decoded output root is cache anyway.
            self._decode_v1mmwx_files([p for p, _ in v1_files], v1_files[0][1], stats)

        if wxgf_files and not self._stop:
            self._convert_wxgf_files(wxgf_files, stats)

        self.progress.emit(stats.scanned_files, stats.recognized)
        self.log.emit(
            f"扫描结束：扫描 {stats.scanned_files} 个文件，识别图片 {stats.recognized} 个，"
            f"V1MMWX {stats.encrypted_v1mmwx} 个，WXGF {stats.wxgf} 个，无法识别/不可读 {stats.unsupported + stats.unreadable} 个。"
        )
        self.finished.emit(stats)
