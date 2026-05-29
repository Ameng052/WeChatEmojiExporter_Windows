from __future__ import annotations

import ctypes
import re
from pathlib import Path

DECODER_RVA = 0x21CA860
SUPPORTED_DECODER_RVAS = {
    # Verified against WeChat 3.9.12.57 / WeChatWin.dll used by the bundled
    # 3.9.12 installer. Other 3.9.x builds may move this function.
    "3.9.12.57": DECODER_RVA,
}


def _normalize_version(version: str | None) -> str:
    if not version:
        return ""
    nums = re.findall(r"\d+", version)[:4]
    return ".".join(nums)


def supported_decoder_versions() -> list[str]:
    return sorted(SUPPORTED_DECODER_RVAS)


def get_decoder_rva_for_version(version: str | None) -> int | None:
    return SUPPORTED_DECODER_RVAS.get(_normalize_version(version))


def is_decoder_supported_version(version: str | None) -> bool:
    return get_decoder_rva_for_version(version) is not None


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def decode_v1mmwx_batch(
    pid: int,
    jobs: list[dict],
    timeout: int = 300,
    *,
    wechat_version: str | None = None,
    decoder_rva: int | None = None,
) -> list[dict]:
    """Decode V1MMWX files to WXGF/standard bytes by calling WeChatWin.dll decoder in a running WeChat 3.9.12 process."""
    if not jobs:
        return []
    if decoder_rva is None and wechat_version:
        decoder_rva = get_decoder_rva_for_version(wechat_version)
        if decoder_rva is None:
            raise RuntimeError(
                "当前微信版本未验证 V1MMWX 解码地址："
                f"{wechat_version}；已验证版本：{', '.join(supported_decoder_versions())}"
            )
    decoder_rva = decoder_rva or DECODER_RVA
    try:
        import frida
    except Exception as e:
        raise RuntimeError("缺少 frida 依赖，请执行 pip install frida，或使用带 frida 的新版 EXE。") from e

    normalized = []
    for j in jobs:
        inp = Path(j["input"])
        out = Path(j["output"])
        out.parent.mkdir(parents=True, exist_ok=True)
        normalized.append({"input": str(inp), "output": str(out), "size": inp.stat().st_size})

    js = """
'use strict';
const decoderRva = ptr('0xDECODER_RVA_HEX');
const base = Process.getModuleByName('WeChatWin.dll').base;
const decodeFn = new NativeFunction(base.add(decoderRva), 'int', ['pointer', 'pointer']);

function decodeOne(job) {
  const f = new File(job.input, 'rb');
  const bytes = f.readBytes(job.size);
  f.close();
  if (bytes.byteLength !== job.size) throw new Error('read size mismatch: ' + bytes.byteLength + ' != ' + job.size);
  const inPtr = Memory.alloc(job.size);
  inPtr.writeByteArray(bytes);
  const inObj = Memory.alloc(0x30);
  inObj.writePointer(inPtr);
  inObj.add(8).writeU32(job.size);
  inObj.add(12).writeU32(job.size);
  inObj.add(16).writeU32(job.size);
  inObj.add(20).writeU32(0);

  const outObj = Memory.alloc(0x40);
  outObj.writeByteArray(new Uint8Array(0x40));
  const ret = decodeFn(inObj, outObj);
  const outPtr = outObj.readPointer();
  let outLen = outObj.add(8).readU32();
  if (outLen <= 0 || outLen > 100 * 1024 * 1024) outLen = outObj.add(12).readU32();
  if (ret === 0 || outPtr.isNull() || outLen <= 0 || outLen > 100 * 1024 * 1024) {
    throw new Error('decode failed ret=' + ret + ' outPtr=' + outPtr + ' outLen=' + outLen);
  }
  const outBytes = outPtr.readByteArray(outLen);
  const fo = new File(job.output, 'wb');
  fo.write(outBytes);
  fo.close();
  return { input: job.input, output: job.output, ret: ret, outLen: outLen };
}

rpc.exports = {
  run: function(jobs) {
    const results = [];
    for (let i = 0; i < jobs.length; i++) {
      try { results.push(Object.assign({ ok: true }, decodeOne(jobs[i]))); }
      catch (e) { results.push({ ok: false, input: jobs[i].input, output: jobs[i].output, error: String(e.stack || e) }); }
    }
    return results;
  }
};
""".replace("0xDECODER_RVA_HEX", "0x%x" % decoder_rva)

    session = frida.attach(pid)
    try:
        script = session.create_script(js)
        script.load()
        return script.exports_sync.run(normalized)
    finally:
        session.detach()
