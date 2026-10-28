// music/ フォルダを読み取り、プレーヤー用の songs.json を作ります。
// GitHub Actions が自動で実行するので、手で動かす必要はありません。
import { readdirSync, statSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, extname, basename, relative, sep } from 'node:path';

const ROOT = process.argv[2] || '.';
const MUSIC = join(ROOT, 'music');
const EXT = new Set(['.mp3', '.m4a', '.aac', '.wav', '.ogg']);

const config = existsSync(join(ROOT, 'config.json'))
  ? JSON.parse(readFileSync(join(ROOT, 'config.json'), 'utf8'))
  : {};
const labels = config.labels || {};
const readJson = name => existsSync(join(ROOT, name)) ? JSON.parse(readFileSync(join(ROOT, name), 'utf8')) : {};
const bpmMap = readJson('bpm.json');
const mixMap = readJson('mix.json');
const tagMap = readJson('tags.json');

function walk(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap(name => {
    if (name.startsWith('.')) return [];
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : EXT.has(extname(name).toLowerCase()) ? [p] : [];
  });
}

const toTitle = name => name.normalize('NFC').replace(/_/g, ' ').trim();
const toSong = p => ({
  title: toTitle(basename(p, extname(p))),
  file: relative(ROOT, p).split(sep).join('/').normalize('NFC'),
  tags: [],
});
const withBpm = s => { const v = bpmMap[s.title]; return v ? { ...s, bpm: v } : s; };
// mix.json（拍の位置・実質の終わり・キー）は scripts/analyze-mix.py で作ります。DJミックスで使います
const withMix = s => { const m = mixMap[s.title]; return m ? { ...s, mix: m } : s; };
const byTitle = (a, b) => a.title.localeCompare(b.title, 'ja', { numeric: true });

// bpm.json（曲名 → BPM）は scripts/measure-bpm.py で作ります
const all = walk(MUSIC).map(toSong).map(withBpm).map(withMix).sort(byTitle);

// tags.json（タグ名 → 曲名の一覧）を各曲に付ける
const byName = new Map(all.map(s => [s.title, s]));
for (const [tag, titles] of Object.entries(tagMap)) {
  for (const t of titles) {
    const s = byName.get(toTitle(t));
    if (!s) { console.warn(`tags.json: 「${t}」という曲が見つかりません（#${tag}）`); continue; }
    if (!s.tags.includes(tag)) s.tags.push(tag);
  }
}

// lyrics/曲名.txt があれば、その曲に歌詞を付ける（プレーヤーが必要なときに読み込む）
const LYRICS = join(ROOT, 'lyrics');
if (existsSync(LYRICS)) {
  for (const name of readdirSync(LYRICS)) {
    if (extname(name).toLowerCase() !== '.txt') continue;
    const s = byName.get(toTitle(basename(name, extname(name))));
    if (!s) { console.warn(`lyrics: 「${name}」に合う曲が見つかりません`); continue; }
    s.lyrics = 'lyrics/' + name.normalize('NFC');
  }
}

const groups = new Map();
for (const s of all) {
  const parts = s.file.split('/');
  if (parts.length > 2) {
    const id = parts[1];
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(s);
  }
}

// 共通フォルダ（初期値 common）の曲は、ほかのすべてのプレイリストにも入れる
const sharedId = config.shared || 'common';
const shared = groups.get(sharedId) || [];
groups.delete(sharedId);

const playlists = [{ id: 'all', label: labels.all || 'すべての曲', songs: all }];
// config.json の labels に書いた順で並べ、書いていないフォルダは後ろに名前順で並べる
const rank = id => { const i = Object.keys(labels).indexOf(id); return i < 0 ? 1e9 : i; };
for (const [id, songs] of [...groups].sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]))) {
  playlists.push({ id, label: labels[id] || id, songs: [...songs, ...shared].sort(byTitle) });
}

const out = { generatedAt: new Date().toISOString(), schedule: config.schedule || [], tags: Object.keys(tagMap), playlists };
writeFileSync(join(ROOT, 'songs.json'), JSON.stringify(out, null, 1));
console.log(`songs.json: ${all.length} 曲 / ${playlists.length} プレイリスト`);
