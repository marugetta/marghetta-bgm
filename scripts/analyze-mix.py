# DJミックス用に、各曲の「拍の位置」「実質の終わり」「キー」を測って mix.json に書き込みます。
# 測っていない曲だけを測ります（--all ですべて測り直し）。
# 必要なもの: Python 3, ffmpeg, librosa（pip install librosa）
#   python3 scripts/analyze-mix.py
import json, sys, unicodedata
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else Path('.')
EXT = {'.mp3', '.m4a', '.aac', '.wav', '.ogg'}
OUT = ROOT / 'mix.json'

# キー判定用（Krumhansl のキープロファイル）と Camelot 表記
MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
CAMELOT_MAJOR = ['8B', '3B', '10B', '5B', '12B', '7B', '2B', '9B', '4B', '11B', '6B', '1B']  # C, C#, D …
CAMELOT_MINOR = ['5A', '12A', '7A', '2A', '9A', '4A', '11A', '6A', '1A', '8A', '3A', '10A']  # Cm, C#m, Dm …

def title_of(p):  # build-songs.mjs と同じ曲名の作り方
    return unicodedata.normalize('NFC', p.stem).replace('_', ' ').strip()

def analyze(path):
    import librosa, numpy as np
    y, sr = librosa.load(path, sr=22050, mono=True)
    hop = 256
    dur = len(y) / sr

    # 拍：まず曲全体のテンポの目安を出す
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    _, beats = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop)
    times = librosa.frames_to_time(beats, sr=sr, hop_length=hop)
    period0 = float(np.polyfit(np.arange(len(times)), times, 1)[0])
    fps = sr / hop
    S = np.abs(librosa.stft(y, hop_length=hop))
    low = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[:40]), sr=sr, hop_length=hop)
    # キック：打楽器の成分（HPSS）の 30〜160Hz だけを見る（裏拍のベースやハイハットに引っぱられないように）
    _, P = librosa.decompose.hpss(S)
    kick = librosa.onset.onset_strength(S=librosa.amplitude_to_db(P[3:15]), sr=sr, hop_length=hop)

    # 区間ごとの拍の格子：拍検出（キックを拾う）で見つけた拍のうち、その区間のものに直線を当てはめる。
    # AIで作った曲はテンポがわずかに揺れることがあるので、つなぐ所（イントロとアウトロ）でそれぞれ合わせる
    def fit(t0, t1):
        t0, t1 = max(0.0, t0), min(dur, t1)
        tb = times[(times >= t0) & (times <= t1)]
        if len(tb) < 16:
            tb = times
        n = np.round((tb - tb[0]) / period0)  # 抜けた拍があっても番号がずれないように、目安のテンポで番号を振る
        period, first = np.polyfit(n, tb, 1)
        # 位相の微調整：拍の位置を ±半拍の範囲で 1ms ずつ動かし、キックにいちばん重なる位置にする
        def kick_at(ph):
            idx = (np.arange(first + ph, t1, period) * fps).astype(int)
            idx = idx[(idx >= 0) & (idx < len(kick))]
            return kick[idx].mean() if len(idx) else 0
        first += max(np.arange(-period / 2, period / 2, 0.001), key=kick_at)
        first -= period * np.floor((first - t0) / period)
        # 小節の頭：4拍のうち、低音の立ち上がりがいちばん強い拍を1拍目とみなす
        grid = np.arange(first, t1, period)
        idx = np.clip((grid * fps).astype(int), 0, len(low) - 1)
        k = int(np.argmax([low[idx[i::4]].mean() for i in range(4)]))
        return {'beat': round(float(period), 5), 'downbeat': round(float(grid[k]), 3)}

    # 音の始まりと実質の終わり（フェードアウトの小さい部分は除く）
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    loud = np.median(rms[rms > 0]) if np.any(rms > 0) else 0
    on = np.nonzero(rms > loud * 0.1)[0]
    start = float(librosa.frames_to_time(on[0], sr=sr, hop_length=hop)) if len(on) else 0.0
    end = float(librosa.frames_to_time(on[-1], sr=sr, hop_length=hop)) if len(on) else dur

    # キー
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=2048).mean(axis=1)
    best = max(((np.corrcoef(np.roll(prof, k), chroma)[0, 1], k, minor)
                for minor, prof in ((False, MAJOR), (True, MINOR)) for k in range(12)))
    _, k, minor = best
    key = (CAMELOT_MINOR if minor else CAMELOT_MAJOR)[k]

    return {'beat': round(period0, 5), 'start': round(start, 2), 'end': round(end, 2),
            'duration': round(dur, 2), 'key': key,
            'in': fit(start, start + 45), 'out': fit(end - 45, end)}

def job(p):
    try:
        return title_of(p), analyze(str(p))
    except Exception as e:
        print(f'測定できませんでした: {p.name} ({e})', file=sys.stderr)
        return title_of(p), None

if __name__ == '__main__':
    mix = json.loads(OUT.read_text('utf8')) if OUT.exists() else {}
    files = [p for p in sorted((ROOT / 'music').rglob('*'))
             if p.suffix.lower() in EXT and not p.name.startswith('.')]
    todo = files if '--all' in sys.argv else [p for p in files if title_of(p) not in mix]
    print(f'{len(todo)} 曲を測ります')
    with Pool() as pool:
        for title, v in pool.imap_unordered(job, todo):
            if v:
                mix[title] = v
                print(f"in {60 / v['in']['beat']:6.2f} out {60 / v['out']['beat']:6.2f}BPM {v['key']:>3}  start {v['start']:5.1f}  end {v['end']:6.1f}/{v['duration']:6.1f}  {title}", flush=True)
    OUT.write_text(json.dumps(dict(sorted(mix.items())), ensure_ascii=False, indent=1) + '\n', 'utf8')
    print(f'mix.json: {len(mix)} 曲')
