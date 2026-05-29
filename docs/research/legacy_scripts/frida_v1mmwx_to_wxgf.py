import argparse, json, os, sys, time
from pathlib import Path

import frida

DECODER_RVA = 0x21ca860


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pid', type=int, required=True)
    ap.add_argument('--jobs-json', required=True)
    ap.add_argument('--timeout', type=float, default=60)
    args = ap.parse_args()
    jobs = json.loads(Path(args.jobs_json).read_text(encoding='utf-8'))
    # add sizes as JS File API readBytes needs length reliably
    for j in jobs:
        j['size'] = Path(j['input']).stat().st_size
        Path(j['output']).parent.mkdir(parents=True, exist_ok=True)

    js = r'''
'use strict';
const decoderRva = ptr('0xDECODER_RVA_HEX');
const base = Process.getModuleByName('WeChatWin.dll').base;
const decodeFn = new NativeFunction(base.add(decoderRva), 'int', ['pointer', 'pointer']);

function decodeOne(job) {
  const f = new File(job.input, 'rb');
  const bytes = f.readBytes(job.size);
  f.close();
  if (bytes.byteLength !== job.size) {
    throw new Error('read size mismatch: ' + bytes.byteLength + ' != ' + job.size);
  }
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
  // Some internal structs use pointer,length,capacity; keep sane cap.
  if (outLen <= 0 || outLen > 100 * 1024 * 1024) {
    outLen = outObj.add(12).readU32();
  }
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
'''.replace('0xDECODER_RVA_HEX', '0x%x' % DECODER_RVA)

    session = frida.attach(args.pid)
    script = session.create_script(js)
    script.load()
    results = script.exports_sync.run(jobs)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    session.detach()

if __name__ == '__main__':
    main()

