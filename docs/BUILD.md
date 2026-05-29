# 构建与发布

## 1. 准备环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

## 2. 可选二进制依赖

这些文件不要提交到 GitHub 仓库，建议放到 `release_assets/` 或在 GitHub Releases 中发布。

| 文件 | 用途 | 推荐位置 |
|---|---|---|
| `ffmpeg.exe` | WXGF/HEVC 转 PNG/GIF | `release_assets\ffmpeg.exe` 或系统 PATH |
| `WeChatSetup.exe` | UI 内一键启动微信安装器 | `release_assets\WeChatSetup.exe` |

也可以用环境变量指定：

```powershell
$env:FFMPEG_EXE="D:\path\to\ffmpeg.exe"
$env:WECHAT_SETUP="D:\path\to\WeChatSetup.exe"
```

## 3. 单文件便携版（推荐发布）

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean .\WeChatEmojiExporter_Portable.spec
```

输出：

```text
dist\WeChatEmojiExporter_Portable.exe
```

把该 EXE 上传到 GitHub Releases。由于体积较大，不建议提交进 Git 仓库。

## 4. 文件夹版

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean .\WeChatEmojiExporter.spec
```

输出：

```text
dist\WeChatEmojiExporter\WeChatEmojiExporter.exe
```

文件夹版必须完整复制整个 `dist\WeChatEmojiExporter` 目录，不能只复制单独 exe，否则会报：

```text
Failed to load Python DLL ... _internal\python310.dll
```

## 5. GitHub 上传建议

提交仓库源码：

```text
core/
ui/
docs/
main.py
requirements.txt
requirements-dev.txt
WeChatEmojiExporter.spec
WeChatEmojiExporter_Portable.spec
README.md
.gitignore
```

不要提交：

```text
.venv/
build/
dist/
release_assets/
WeChatSetup.exe
ffmpeg.exe
任何微信用户数据/导出表情包
```
