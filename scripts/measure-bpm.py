# music/ の曲のBPM（テンポ）を測って bpm.json に書き込みます。
# 測っていない曲だけを測ります（--all ですべて測り直し）。
# 必要なもの: Python 3, ffmpeg, librosa（pip install librosa）
#   python3 scripts/measure-bpm.py
import json, sys, unicodedata
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else Path('.')
EXT = {'.mp3', '.m4a', '.aac', '.wav', '.ogg'}
OUT = ROOT / 'bpm.json'

def title_of(p):  # build-songs.mjs と同じ曲名の作り方
    return unicodedata.normalize('NFC', p.stem).replace('_', ' ').strip()

def measure(path):
    import librosa, numpy as np
    y, sr = librosa.load(path, sr=22050, mono=True, offset=20, duration=120)
    hop = 128
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    _, beats = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop)
    times = librosa.frames_to_time(beats, sr=sr, hop_length=hop)
    if len(times) < 8:
        return None
    # 拍の時刻に直線を当てはめて、1拍の長さを細かく求める
    period = np.polyfit(np.arange(len(times)), times, 1)[0]
    return round(60 / period)

def job(p):
    try:
        return title_of(p), measure(str(p))
    except Exception as e:
        print(f'測定できませんでした: {p.name} ({e})', file=sys.stderr)
        return title_of(p), None

if __name__ == '__main__':
    bpm = json.loads(OUT.read_text('utf8')) if OUT.exists() else {}
    files = [p for p in sorted((ROOT / 'music').rglob('*'))
             if p.suffix.lower() in EXT and not p.name.startswith('.')]
    todo = files if '--all' in sys.argv else [p for p in files if title_of(p) not in bpm]
    print(f'{len(todo)} 曲を測ります')
    with Pool() as pool:
        for title, v in pool.imap_unordered(job, todo):
            print(f'{v if v else "-":>4}  {title}', flush=True)
            if v:
                bpm[title] = v
    OUT.write_text(json.dumps(dict(sorted(bpm.items())), ensure_ascii=False, indent=1) + '\n', 'utf8')
    print(f'bpm.json: {len(bpm)} 曲')
