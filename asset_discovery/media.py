"""Scene splitting, sampled-frame checks, transcript sidecars and incremental indexing."""
import json
import math
import re
from pathlib import Path
from .core import EXTENSIONS, now, probe, run, sha, read_json, write_json


def bounds(duration, cuts, maximum):
    if maximum <= 0 or duration <= 0:
        raise ValueError('Positive durations required')
    edges = [0.0]
    for cut in sorted(set(float(x) for x in cuts if 0 < float(x) < duration)):
        if cut - edges[-1] >= 0.4 and duration-cut >= 0.4:
            edges.append(cut)
    edges.append(duration)
    result = []
    for a, b in zip(edges, edges[1:]):
        count = max(1, math.ceil((b-a)/maximum))
        result += [(a+(b-a)*i/count, a+(b-a)*(i+1)/count) for i in range(count)]
    return result


def cuts(path, threshold):
    r = run(['ffmpeg', '-nostdin', '-hide_banner', '-i', path, '-an', '-vf',
             f'scale=320:-2,select=gt(scene\\,{threshold}),showinfo', '-vsync', 'vfr', '-f', 'null', '-'])
    return [float(x) for x in re.findall(r'pts_time:([\d.]+)', r.stderr.decode(errors='replace'))]


def sample_frame(path, second, target):
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', second, '-i', path,
         '-frames:v', '1', '-vf', 'scale=640:-2', target])
    pixels = run(['ffmpeg', '-nostdin', '-v', 'error', '-i', target, '-vf', 'scale=64:64,format=gray',
                  '-frames:v', '1', '-f', 'rawvideo', '-']).stdout
    if len(pixels) != 4096:
        raise ValueError('Frame decode did not produce expected pixels')
    lap = [4*pixels[y*64+x]-pixels[y*64+x-1]-pixels[y*64+x+1]-pixels[(y-1)*64+x]-pixels[(y+1)*64+x]
           for y in range(1, 63) for x in range(1, 63)]
    mean = sum(lap)/len(lap)
    return {'dark_fraction': sum(x < 16 for x in pixels)/4096,
            'bright_fraction': sum(x > 240 for x in pixels)/4096,
            'laplacian_variance': sum((x-mean)**2 for x in lap)/len(lap)}


def transcript(path):
    """Read own sidecars: file.ext.srt or file.srt. All timings source-relative."""
    for side in [Path(str(path)+'.srt'), path.with_suffix('.srt')]:
        if side.exists():
            text = side.read_text(encoding='utf-8-sig')
            pattern = r'(\d\d):(\d\d):(\d\d)[,.](\d{3})'
            results = []
            for block in re.split(r'\n\s*\n', text.strip()):
                matches = list(re.finditer(pattern, block))
                if len(matches) < 2:
                    continue
                def seconds(m):
                    h, mi, s, ms = map(int, m.groups())
                    return h*3600+mi*60+s+ms/1000
                results.append({'start': seconds(matches[0]), 'end': seconds(matches[1]),
                                'text': re.sub('<[^>]+>', '', block[matches[1].end():]).strip()})
            return results
    return []


def index(project, roots=None):
    roots = roots or project.config['roots']
    if not roots:
        raise ValueError('Set config roots or pass explicit media paths')
    stats = {'indexed': 0, 'unchanged': 0, 'errors': [], 'missing': 0}
    files = set()
    for root in roots:
        root = Path(root).expanduser().resolve()
        if not root.exists():
            stats['errors'].append({'path': str(root), 'error': 'Root does not exist'})
            continue
        candidates = [root] if root.is_file() else root.rglob('*')
        for p in candidates:
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTENSIONS:
                files.add(p.resolve())
    for path in sorted(files):
        try:
            digest = sha(path)
            sidecars = [Path(str(path)+x) for x in ('.asset.json', '.license.json', '.srt')]+[path.with_suffix('.srt')]
            signature = digest + ''.join(sha(s) for s in sidecars if s.exists())
            signature += json.dumps({k: project.config[k] for k in ('max_segment_seconds', 'scene_threshold')})
            old = project.db.execute('SELECT * FROM assets WHERE path=?', (str(path),)).fetchone()
            if old and old['fingerprint'] == signature:
                stats['unchanged'] += 1
                continue
            import hashlib
            aid = hashlib.sha256(str(path).encode()).hexdigest()[:20]
            info = probe(path)
            provenance = read_json(str(path)+'.license.json') if Path(str(path)+'.license.json').exists() else {'source': 'local', 'rights': 'user_supplied_unverified'}
            metadata = read_json(str(path)+'.asset.json') if Path(str(path)+'.asset.json').exists() else {}
            info.update(provenance=provenance, metadata=metadata, indexed_at=now())
            spans = bounds(info['duration'], cuts(path, project.config['scene_threshold']) if info['kind']=='video' else [], project.config['max_segment_seconds'])
            captions = transcript(path)
            rows = []
            for i, (a, b) in enumerate(spans):
                sid = f'{aid}-{i:05d}'
                folder = project.path/'frames'/sid
                folder.mkdir(parents=True, exist_ok=True)
                frames, measures = [], []
                if info['kind'] == 'video':
                    for n, ratio in enumerate((0.15, 0.5, 0.85)):
                        second = a+(b-a)*ratio
                        target = folder/f'{n}.jpg'
                        measures.append(sample_frame(path, second, target))
                        frames.append({'path': str(target), 'second': second})
                quality = {k: sum(m[k] for m in measures)/len(measures) for k in measures[0]} if measures else {}
                audio = {}
                if info['has_audio']:
                    output = run(['ffmpeg', '-nostdin', '-hide_banner', '-ss', a, '-t', b-a, '-i', path,
                                  '-vn', '-af', 'volumedetect', '-f', 'null', '-']).stderr.decode(errors='replace')
                    for key in ('mean_volume', 'max_volume'):
                        m = re.search(key+r': ([\-\d.]+) dB', output)
                        if m:
                            audio[key] = float(m[1])
                segment_meta = [s for s in metadata.get('segments', []) if float(s['start']) < b and float(s['end']) > a]
                caption = ' '.join(c['text'] for c in captions if c['start'] < b and c['end'] > a)
                description = ' '.join(str(s.get('description', '')) for s in segment_meta)
                review = next((s.get('review') for s in segment_meta if s.get('review')), None)
                if review:
                    validate_review(review)
                data = {'frames': frames, 'quality': quality, 'audio': audio, 'transcript': caption,
                        'description': description, 'review': review,
                        'text': ' '.join([path.stem, str(metadata.get('description', '')), ' '.join(metadata.get('tags', [])), description, caption])}
                rows.append((sid, aid, a, b, json.dumps(data, ensure_ascii=False)))
            with project.db:
                project.db.execute('DELETE FROM segments WHERE asset_id=?', (aid,))
                project.db.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?,?,?)', (aid, str(path), digest, signature, json.dumps(info, ensure_ascii=False)))
                project.db.executemany('INSERT INTO segments VALUES(?,?,?,?,?)', rows)
            stats['indexed'] += 1
        except Exception as e:
            # An unsuccessful refresh must never keep a previously valid-looking stale index.
            with project.db:
                old = project.db.execute('SELECT id FROM assets WHERE path=?', (str(path),)).fetchone()
                if old:
                    project.db.execute('DELETE FROM segments WHERE asset_id=?', (old['id'],))
                    project.db.execute('DELETE FROM assets WHERE id=?', (old['id'],))
            stats['errors'].append({'path': str(path), 'error': str(e)})
    for row in project.db.execute('SELECT id,path FROM assets').fetchall():
        if not Path(row['path']).exists():
            with project.db:
                project.db.execute('DELETE FROM segments WHERE asset_id=?', (row['id'],))
                project.db.execute('DELETE FROM assets WHERE id=?', (row['id'],))
            stats['missing'] += 1
    return stats


def validate_review(review):
    if not isinstance(review, dict) or not isinstance(review.get('description'), str) or not review['description'].strip():
        raise ValueError('Review requires nonempty description')
    for key in ('aesthetic', 'usability', 'confidence'):
        value = review.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f'Review {key} must be 0..1')
    for key in ('reject', 'synthetic', 'has_people', 'has_logos'):
        if not isinstance(review.get(key), bool):
            raise ValueError(f'Review {key} must be boolean')
    if not isinstance(review.get('tags'), list) or any(not isinstance(x, str) for x in review['tags']):
        raise ValueError('Review tags must be strings')
    return review


def import_reviews(project, path):
    data = read_json(path)
    lookup = {s['id']: s for s in project.segments()}
    for item in data:
        s = lookup[item['id']]
        if item.get('sha256') != s['sha256']:
            raise ValueError('Review content hash mismatch')
        validate_review(item['review'])
    for item in data:
        s = lookup[item['id']]
        raw = json.loads(project.db.execute('SELECT data FROM segments WHERE id=?', (s['id'],)).fetchone()[0])
        raw['review'] = dict(item['review'], reviewed_at=now(), method='agent_or_human_import')
        raw.pop('embedding', None)
        raw.pop('embedding_model', None)
        project.update_segment(s['id'], raw)
    return {'imported': len(data)}
