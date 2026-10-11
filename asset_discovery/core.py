"""Local project state. Standard library only; media tools are external."""
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DEFAULT = {
    'version': 2, 'roots': [], 'max_segment_seconds': 8, 'scene_threshold': 0.32,
    'min_video_height': 720, 'fps': 30, 'width': 1920, 'height': 1080,
    'min_relevance': 0.12, 'require_review': True,
    'online': {'enabled': False, 'contact': '', 'max_results': 5,
               'max_download_mb': 150, 'request_interval': 1.1,
               'license_mode': 'commercial_edit', 'intended_use': 'web_video',
               'pixabay_editors_choice': False, 'freesound_api_use': 'unconfirmed', 'freesound_agreement_reference': ''},
    'ai': {'base_url': 'http://127.0.0.1:1234/v1', 'model': '',
           'embedding_model': '', 'transcription_model': '', 'audio_model': '',
           'key_env': 'ASSET_AI_KEY', 'allow_remote_upload': False}
}
EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aiff', '.aac', '.opus', '.ogv', '.aif'}

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def run(args, timeout=900):
    result = subprocess.run([str(x) for x in args], capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr.decode(errors="replace")[-1800:]}')
    return result

def probe(path):
    data = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path]).stdout)
    streams = data['streams']
    video = next((s for s in streams if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
    audio = next((s for s in streams if s['codec_type'] == 'audio'), None)
    duration = float(data.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0 or not (video or audio):
        raise ValueError(f'Not a finite duration AV file: {path}')
    rate = video.get('avg_frame_rate', '0/1') if video else '0/1'
    n, d = rate.split('/')
    return {'duration': duration, 'kind': 'video' if video else 'audio',
            'width': video.get('width', 0) if video else 0,
            'height': video.get('height', 0) if video else 0,
            'fps': float(n) / float(d) if float(d) else 0,
            'has_audio': bool(audio), 'sample_rate': audio.get('sample_rate') if audio else None}

class Project:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.config = read_json(self.path / 'config.json')
        self.db = sqlite3.connect(self.path / 'index.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, path TEXT UNIQUE, sha TEXT, fingerprint TEXT, data TEXT);
          CREATE TABLE IF NOT EXISTS segments(id TEXT PRIMARY KEY, asset_id TEXT, start REAL, end REAL, data TEXT);
          CREATE INDEX IF NOT EXISTS by_asset ON segments(asset_id);
        ''')

    @classmethod
    def init(cls, path):
        path = Path(path).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        if (path / 'config.json').exists():
            raise ValueError('Project already exists; configuration was not overwritten')
        write_json(path / 'config.json', DEFAULT)
        return cls(path)

    def segments(self):
        rows = self.db.execute('SELECT s.*, a.path, a.sha, a.data AS asset_data FROM segments s JOIN assets a ON a.id=s.asset_id')
        out = []
        for r in rows:
            d = json.loads(r['data'])
            d.update(id=r['id'], asset_id=r['asset_id'], start=r['start'], end=r['end'],
                     path=r['path'], sha256=r['sha'], asset=json.loads(r['asset_data']))
            out.append(d)
        return out

    def update_segment(self, ident, data):
        self.db.execute('UPDATE segments SET data=? WHERE id=?', (json.dumps(data, ensure_ascii=False), ident))
        self.db.commit()


def terms(text):
    text = str(text).lower()
    result = re.findall(r'[a-z0-9]+', text)
    for group in re.findall(r'[\u4e00-\u9fff]+', text):
        result += [group[i:i+2] for i in range(len(group)-1)] or [group]
    return set(result)

def cosine(a, b):
    if len(a) != len(b) or not a:
        return 0.0
    den = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / den if den else 0.0

def clean_html(value):
    import html
    return html.unescape(re.sub('<[^>]*>', ' ', str(value))).strip()
