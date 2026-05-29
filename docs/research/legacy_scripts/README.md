# 研究脚本归档

这里保留早期验证 V1MMWX / WXGF 流程时使用的独立脚本，仅作技术参考，不属于主程序运行依赖。

主程序已经把相关能力整合进：

- `core/v1mmwx_decoder.py`
- `core/wxgf_converter.py`
- `core/scanner.py`

注意：

- `frida_v1mmwx_to_wxgf.py` 使用固定 RVA，仍只适合已验证的微信 3.9.12.57。
- `wxgf_to_standard.py` 是旧版 OpenCV/Pillow 实验脚本；主程序已改用 ffmpeg，依赖更少、打包更稳定。
