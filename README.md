# 微信自定义表情包批量导出工具（Windows / PySide6）

本工具用于本地离线扫描微信 3.9.12 用户目录中的 `FileStorage\CustomEmotion`，识别、预览、选择并批量导出用户自定义表情包。工具只扫描微信自定义表情目录，不会把 `FileStorage` 下的聊天图片、下载图片、临时图片一起导出。

## 功能范围

- 支持标准图片：PNG、JPG/JPEG、GIF、WEBP、BMP、APNG；
- 支持无后缀文件按文件头/魔数识别并导出为正确扩展名；
- 支持微信 3.9.12.57 的 `V1MMWX -> WXGF -> PNG/GIF` 本地转换；
- 支持直接扫描到的 WXGF 文件转换；
- 支持网格预览、格式筛选、排序、搜索、全选、反选、取消选择；
- 支持导出选中/导出全部；
- 支持 SHA256 去重，重复文件默认跳过；
- 支持导出 JSON 日志。

## 安全边界

- 只读扫描、复制导出，不修改、不删除、不覆盖微信原始文件；
- 不读取聊天记录、联系人、账号凭证、Cookie、Token、数据库密钥；
- 不上传网络；
- 微信登录只调用官方客户端，由用户手动扫码确认。

> 注意：程序可以启动微信 3.9.12 及以下版本用于官方扫码登录和文件落盘；但 V1MMWX 转换地址目前只验证 `3.9.12.57`。其他 3.9.x 小版本会被提示未验证，避免错误调用。

## 目录结构

```text
wechat_emoji_exporter_app/
  main.py
  requirements.txt
  WeChatEmojiExporter.spec
  WeChatSetup.exe
  core/
    models.py
    format_detector.py
    utils.py
    process_utils.py
    wechat_env.py
    scanner.py
    exporter.py
    v1mmwx_decoder.py
    wxgf_converter.py
  ui/
    main_window.py
    widgets.py
```

## 运行（也可以用我打包好的）

```powershell
cd ..\wechat_emoji_exporter_app
.\.venv\Scripts\python.exe main.py
```

首次环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 使用步骤

1. 点击“检测微信”或“选择微信安装目录”；

2. 如未安装兼容版本，可点击“安装微信 3.9.12”；

3. 点击“启动微信并扫码登录”，在微信官方窗口中扫码确认；

   ![image-20260529221148425](D:\Program Files (x86)\typora\picture\image-20260529221148425.png)

4. 选择微信文件目录，例如：
   - `...\WeChat Files\wxid_xxx`
   - `...\WeChat Files\wxid_xxx\FileStorage`
   - `...\WeChat Files\wxid_xxx\FileStorage\CustomEmotion`

5. 勾选“扫描时转换 V1MMWX”，自动读取 PID；

6. 点击“开始扫描”；

7. 在网格中筛选、搜索、选择表情；

8. 点击“导出选中”或“导出全部”。

   ![image-20260529221254774](D:\Program Files (x86)\typora\picture\image-20260529221254774.png)

## 导出结果

导出文件命名：

```text
emoji_0001_哈希前8位.png
emoji_0002_哈希前8位.gif
```

日志：

```text
export_log.json
```

日志记录原始路径、导出路径、格式、大小、SHA256、是否重复、状态、失败原因。

## 快速上手

### 方式一：单文件便携版（推荐）

只需要复制一个 EXE 到其他电脑：

```powershell
cd ..\wechat_emoji_exporter_app
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean .\WeChatEmojiExporter_Portable.spec
```

输出：

```text
dist\WeChatEmojiExporter_Portable.exe
```

### 方式二：文件夹版

```powershell
cd ..\wechat_emoji_exporter_app
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean .\WeChatEmojiExporter.spec
```

输出：

```text
dist\WeChatEmojiExporter\WeChatEmojiExporter.exe
```

文件夹版必须完整复制整个 `dist\WeChatEmojiExporter` 文件夹，不能只复制单独的 exe；否则其他电脑会报 `Failed to load Python DLL ... _internal\python310.dll`。

## 测试建议

1. 标准图片目录：确认 PNG/GIF/WEBP 等可识别和预览；
2. 无后缀图片：复制 PNG 去掉扩展名，应识别为 PNG 并导出 `.png`；
3. 微信原始目录：确认 V1MMWX 数量正确，3.9.12.57 可转换；
4. 停止扫描：转换过程中点击停止，应在当前批次后停止后续批次；
5. 重复导出：第二次导出同一批图片，应跳过导出目录已有重复文件；
6. 中文路径：微信目录和导出目录包含中文时应正常；V1MMWX 中间目录会自动切换到 ASCII 安全路径。
