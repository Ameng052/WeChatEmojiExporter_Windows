from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot


from .models import EmojiItem, ExportRecord
from .format_detector import detect_file
from .utils import sha256_file


class ExportWorker(QObject):
    progress = Signal(int, int)       # done, total
    log = Signal(str)
    finished = Signal(object)         # summary dict

    def __init__(self, items: list[EmojiItem], export_dir: str, skip_duplicates: bool = True):
        super().__init__()
        self.items = items
        self.export_dir = Path(export_dir)
        self.skip_duplicates = skip_duplicates
        self._stop = False

    @Slot()
    def stop(self):
        self._stop = True

    def _write_logs(self, records: list[ExportRecord], summary: dict):
        self.export_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": summary,
            "records": [r.to_dict() for r in records],
        }
        json_path = self.export_dir / "export_log.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["json_log"] = str(json_path)

    def _load_existing_hashes(self) -> dict[str, Path]:
        """Hash already-exported image files so repeated exports skip duplicates."""
        out: dict[str, Path] = {}
        if not self.export_dir.exists():
            return out
        supported_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        for path in self.export_dir.iterdir():
            if self._stop:
                break
            if not path.is_file() or path.name.lower() == "export_log.json":
                continue
            if path.suffix.lower() not in supported_ext:
                continue
            try:
                info = detect_file(path)
                if info.supported:
                    out.setdefault(sha256_file(path), path)
            except Exception:
                continue
        if out:
            self.log.emit(f"已读取导出目录现有图片 {len(out)} 个，用于去重。")
        return out


    @Slot()
    def run(self):
        self.export_dir.mkdir(parents=True, exist_ok=True)
        records: list[ExportRecord] = []
        seen_hashes: dict[str, Path] = self._load_existing_hashes() if self.skip_duplicates else {}
        total = len(self.items)
        success = duplicate = failed = 0
        started = datetime.now().isoformat(timespec="seconds")
        for i, item in enumerate(self.items, 1):
            if self._stop:
                self.log.emit("用户停止导出。")
                break
            out_path = None
            try:
                original_path = item.original_path or item.source_path
                is_dup = item.sha256 in seen_hashes
                if is_dup and self.skip_duplicates:
                    duplicate += 1
                    rec = ExportRecord(i, original_path, str(seen_hashes[item.sha256]), item.file_type, item.size, item.sha256, True, "duplicate_skipped")
                    records.append(rec)
                    self.log.emit(f"跳过重复：{original_path}")
                    self.progress.emit(i, total)
                    continue
                name = f"emoji_{i:04d}_{item.sha256[:8]}.{item.ext}"
                out_path = self.export_dir / name
                # Extremely unlikely, but stable and non-overwriting.
                n = 2
                while out_path.exists():
                    out_path = self.export_dir / f"emoji_{i:04d}_{item.sha256[:8]}_{n}.{item.ext}"
                    n += 1
                shutil.copy2(item.source_path, out_path)
                seen_hashes[item.sha256] = out_path
                success += 1
                records.append(ExportRecord(i, original_path, str(out_path), item.file_type, item.size, item.sha256, is_dup, "success"))
                if i <= 10 or i % 50 == 0:
                    self.log.emit(f"导出成功：{out_path}")
            except Exception as e:
                failed += 1
                original_path = item.original_path or item.source_path
                records.append(ExportRecord(i, original_path, str(out_path) if out_path else None, item.file_type, item.size, item.sha256, False, "failed", str(e)))
                self.log.emit(f"导出失败：{original_path}，原因：{e}")
            self.progress.emit(i, total)
        summary = {
            "started_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "export_dir": str(self.export_dir),
            "selected_export_count": total,
            "success": success,
            "duplicate_skipped": duplicate,
            "failed": failed,
            "stopped": self._stop,
        }
        try:
            self._write_logs(records, summary)
        except Exception as e:
            self.log.emit(f"日志写入失败：{e}")
        self.finished.emit(summary)
