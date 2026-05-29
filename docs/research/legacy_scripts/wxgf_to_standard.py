import argparse, hashlib, json, tempfile
from pathlib import Path

import cv2
from PIL import Image

MIN_RATIO = 0.6


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def find_partitions(data: bytes):
    if len(data) < 16 or data[:4] != b'wxgf':
        raise ValueError('not wxgf')
    header_len = data[4]
    if header_len >= len(data):
        raise ValueError('invalid wxgf header length')
    for pat in (b'\x00\x00\x00\x01', b'\x00\x00\x01'):
        ret = []
        offset = 0
        while header_len + offset <= len(data):
            idx = data.find(pat, header_len + offset)
            if idx < 0:
                break
            if idx < 4:
                offset = idx - header_len + 1
                continue
            length = int.from_bytes(data[idx - 4:idx], 'big')
            if length > 0 and idx + length <= len(data):
                ret.append({'offset': idx, 'size': length, 'ratio': length / len(data)})
                offset = idx - header_len + length
            else:
                offset = idx - header_len + 1
        if ret:
            return ret
    raise ValueError('no h265 partition found')


def decode_h265_first_frame(raw: bytes):
    with tempfile.NamedTemporaryFile(suffix='.h265', delete=False) as tf:
        temp = Path(tf.name)
        tf.write(raw)
    try:
        cap = cv2.VideoCapture(str(temp))
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            raise ValueError('opencv cannot decode h265 frame')
        # BGR -> RGB
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame)
    finally:
        try:
            temp.unlink()
        except Exception:
            pass


def decode_h265_all_frames(raw: bytes):
    frames = []
    with tempfile.NamedTemporaryFile(suffix='.h265', delete=False) as tf:
        temp = Path(tf.name)
        tf.write(raw)
    try:
        cap = cv2.VideoCapture(str(temp))
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(frame))
        cap.release()
        if not frames:
            raise ValueError('opencv cannot decode h265 frames')
        return frames
    finally:
        try:
            temp.unlink()
        except Exception:
            pass


def wxgf_to_image(src: Path, out_dir: Path, name_prefix: str):
    data = src.read_bytes()
    # Some V1MMWX files decode directly to a standard image container, not WXGF.
    direct_ext = None
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        direct_ext = 'png'
    elif data.startswith(b'\xff\xd8\xff'):
        direct_ext = 'jpg'
    elif data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        direct_ext = 'gif'
    elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        direct_ext = 'webp'
    if direct_ext:
        out_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        out = out_dir / f'{name_prefix}.{direct_ext}'
        out.write_bytes(data)
        frames = 1
        if direct_ext == 'gif':
            try:
                im = Image.open(out)
                frames = getattr(im, 'n_frames', 1)
            except Exception:
                frames = 1
        return {'ok': True, 'source': str(src), 'output': str(out), 'type': direct_ext, 'sha256': digest, 'direct_standard': True, 'frames': frames, 'size': out.stat().st_size}

    parts = find_partitions(data)
    max_idx, max_part = max(enumerate(parts), key=lambda kv: kv[1]['ratio'])
    like_anime = len(parts) > 1 and max_part['ratio'] < MIN_RATIO
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    if like_anime:
        mask_parts = [p for i, p in enumerate(parts) if i % 2 == 0]
        anime_parts = [p for i, p in enumerate(parts) if i % 2 == 1]
        # WXGF animated stickers store per-frame HEVC partitions. Later partitions
        # may omit VPS/SPS/PPS, so decode them as one concatenated bytestream,
        # matching the ffmpeg reference implementation.
        anime_stream = b''.join(data[p['offset']:p['offset'] + p['size']] for p in anime_parts)
        mask_stream = b''.join(data[p['offset']:p['offset'] + p['size']] for p in mask_parts)
        frames = decode_h265_all_frames(anime_stream)
        try:
            masks = decode_h265_all_frames(mask_stream) if mask_stream else []
        except Exception:
            masks = []
        if masks:
            merged = []
            for i, img in enumerate(frames):
                m = masks[min(i, len(masks) - 1)].convert('L').resize(img.size)
                rgba = img.convert('RGBA')
                rgba.putalpha(m)
                merged.append(rgba)
            frames = merged
        if not frames:
            raise ValueError('no gif frames decoded')
        out = out_dir / f'{name_prefix}_{digest[:8]}.gif'
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=80, loop=0, disposal=2)
        return {'ok': True, 'source': str(src), 'output': str(out), 'type': 'gif', 'sha256': digest, 'partitions': parts, 'like_anime': True, 'frames': len(frames), 'size': out.stat().st_size}
    else:
        p = max_part
        try:
            img = decode_h265_first_frame(data[p['offset']:p['offset'] + p['size']])
        except Exception:
            # Fallback: some files are misclassified by ratio but still need the
            # parameter sets from adjacent partitions.
            stream = b''.join(data[x['offset']:x['offset'] + x['size']] for x in parts)
            img = decode_h265_first_frame(stream)
        out = out_dir / f'{name_prefix}_{digest[:8]}.png'
        img.save(out)
        return {'ok': True, 'source': str(src), 'output': str(out), 'type': 'png', 'sha256': digest, 'partitions': parts, 'like_anime': False, 'frames': 1, 'size': out.stat().st_size}


def main():
    ap = argparse.ArgumentParser(description='Convert WeChat WXGF to PNG/GIF using OpenCV+Pillow')
    ap.add_argument('--input-dir', required=True)
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--log', required=True)
    args = ap.parse_args()
    in_dir = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    results = []
    files = sorted([p for p in in_dir.rglob('*') if p.is_file()])
    for idx, p in enumerate(files, 1):
        try:
            # Preserve upstream stable stem, e.g. emoji_0001_9ff3fd10.wxgf
            # -> emoji_0001_9ff3fd10.png / .gif
            results.append(wxgf_to_image(p, out_dir, p.stem))
        except Exception as e:
            results.append({'ok': False, 'source': str(p), 'error': str(e)})
    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    Path(args.log).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    ok = sum(1 for r in results if r.get('ok'))
    print(json.dumps({'input_files': len(files), 'converted': ok, 'failed': len(files)-ok, 'log': args.log}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
