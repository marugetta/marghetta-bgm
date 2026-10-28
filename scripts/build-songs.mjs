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

function walk(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap(name => {
    if (name.startsWith('.')) return [];
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : EXT.has(extname(name).toLowerCase()) ? [p] : [];
  });
}

const toSong = p => ({
  title: basename(p, extname(p)).normalize('NFC').replace(/_/g, ' ').trim(),
  file: relative(ROOT, p).split(sep).join('/').normalize('NFC'),
});
const byTitle = (a, b) => a.title.localeCompare(b.title, 'ja', { numeric: true });

const all = walk(MUSIC).map(toSong).sort(byTitle);
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

const out = { generatedAt: new Date().toISOString(), schedule: config.schedule || [], playlists };
writeFileSync(join(ROOT, 'songs.json'), JSON.stringify(out, null, 1));
console.log(`songs.json: ${all.length} 曲 / ${playlists.length} プレイリスト`);
