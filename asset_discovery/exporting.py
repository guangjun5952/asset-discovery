"""Review packets and rendered interchange assets; no shell interpolation."""
import base64
import csv
import html
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from .core import probe, run, sha, write_json
from .planning import validate_plan
from .rights import PROVIDERS, policy


def review_packet(project, destination, limit=20):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    selected = [s for s in project.segments() if not s.get('review')][:max(1, min(limit, 100))]
    packet, template, cards = [], [], []
    for s in selected:
        preview = destination/(s['id']+('.mp4' if s['asset']['kind']=='video' else '.wav'))
        args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', s['start'], '-t', s['end']-s['start'], '-i', s['path']]
        if s['asset']['kind']=='video':
            args += ['-map', '0:v:0', '-map', '0:a:0?', '-vf', 'scale=640:-2', '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart']
        else:
            args += ['-vn', '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le']
        run(args+[preview])
        packet.append({'id': s['id'], 'sha256': s['sha256'], 'source_path': s['path'],
                       'source_in': s['start'], 'source_out': s['end'], 'frames': s['frames'],
                       'preview': str(preview), 'transcript': s['transcript'], 'quality': s['quality'], 'audio': s['audio']})
        template.append({'id': s['id'], 'sha256': s['sha256'], 'review': {'description': '', 'tags': [], 'aesthetic': 0,
                         'usability': 0, 'confidence': 0, 'reject': False, 'synthetic': False, 'has_people': False, 'has_logos': False}})
        provenance = s['asset']['provenance']
        credit = html.escape(' · '.join(str(provenance.get(k, '')) for k in ('provider', 'author', 'source_page', 'license_url')))
        pictures = ''.join('<img src="data:image/jpeg;base64,'+base64.b64encode(Path(f['path']).read_bytes()).decode()+'">' for f in s['frames'])
        tag = 'video' if s['asset']['kind']=='video' else 'audio'
        cards.append(f'<article><h2>{html.escape(Path(s["path"]).name)}</h2><p>{s["start"]:.3f}–{s["end"]:.3f}s · {s["id"]}</p><{tag} controls src="{html.escape(preview.name)}"></{tag}><div>{pictures}</div><p>{html.escape(s["text"])}</p><p>{credit}</p></article>')
    write_json(destination/'review-packet.json', packet)
    write_json(destination/'review-template.json', template)
    (destination/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>素材审片</title><style>body{background:#111;color:#eee;font:16px system-ui;margin:32px}article{background:#222;padding:20px;margin:20px 0;border-radius:12px}img{width:30%;margin:1%}video{max-width:640px;width:100%}p{overflow-wrap:anywhere}</style><h1>素材审片</h1><p>测试指标不代替观看；播放片段确认动作、录屏小字和音效。review-template.json 填完后用 import-review 导入。</p>'+''.join(cards), encoding='utf-8')
    return {'segments': len(packet), 'html': str(destination/'review.html'), 'packet': str(destination/'review-packet.json')}


def element(parent, tag, text=None, **attrs):
    child = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        child.text = str(text)
    return child


def xml_timeline(manifest, destination):
    """Final Cut Pro 7 XML (xmeml), supported by Resolve; all media normalized CFR."""
    fps = manifest['fps']
    root = ET.Element('xmeml', version='5')
    seq = element(root, 'sequence', id='asset-discovery-sequence')
    element(seq, 'name', 'Asset Discovery')
    element(seq, 'duration', manifest['durationInFrames'])
    def rate(parent):
        r = element(parent, 'rate')
        element(r, 'timebase', fps)
        element(r, 'ntsc', 'FALSE')
    rate(seq)
    media = element(seq, 'media')
    video = element(media, 'video')
    fmt = element(video, 'format')
    characteristics = element(fmt, 'samplecharacteristics')
    rate(characteristics)
    element(characteristics, 'width', manifest['width'])
    element(characteristics, 'height', manifest['height'])
    element(characteristics, 'pixelaspectratio', 'square')
    element(characteristics, 'fielddominance', 'none')
    vtrack = element(video, 'track')
    audio = element(media, 'audio')
    element(audio, 'numOutputChannels', 2)
    atracks = [element(audio, 'track') for _ in range(4)]
    def clip(track, entry, kind, suffix, file_full, channel=1):
        node = element(track, 'clipitem', id=entry['id']+'-'+suffix)
        element(node, 'name', entry['id'])
        element(node, 'duration', entry['durationInFrames'])
        rate(node)
        element(node, 'start', entry['from'])
        element(node, 'end', entry['from']+entry['durationInFrames'])
        element(node, 'in', 0)
        element(node, 'out', entry['durationInFrames'])
        f = element(node, 'file', id='file-'+entry['id'])
        if file_full:
            element(f, 'name', Path(entry['absolutePath']).name)
            element(f, 'pathurl', Path(entry['absolutePath']).as_uri())
            rate(f)
            element(f, 'duration', entry['durationInFrames'])
            m = element(f, 'media')
            if entry['kind']=='video':
                v = element(m, 'video')
                c = element(v, 'samplecharacteristics')
                rate(c)
                element(c, 'width', manifest['width'])
                element(c, 'height', manifest['height'])
                element(c, 'pixelaspectratio', 'square')
                element(c, 'fielddominance', 'none')
            if entry['hasAudio']:
                a = element(m, 'audio')
                c = element(a, 'samplecharacteristics')
                element(c, 'depth', 16)
                element(c, 'samplerate', 48000)
                element(a, 'channelcount', 2)
        source = element(node, 'sourcetrack')
        element(source, 'mediatype', kind)
        element(source, 'trackindex', channel)
    for e in manifest['clips']:
        if e['kind']=='video':
            clip(vtrack, e, 'video', 'v', True)
            if e['hasAudio']:
                clip(atracks[0], e, 'audio', 'a1', False, 1)
                clip(atracks[1], e, 'audio', 'a2', False, 2)
        else:
            clip(atracks[2], e, 'audio', 'a1', True, 1)
            clip(atracks[3], e, 'audio', 'a2', False, 2)
    ET.indent(root)
    ET.ElementTree(root).write(destination, encoding='utf-8', xml_declaration=True)


def export(project, selection, destination, allow_partial=False):
    if selection.get('unresolved') and not allow_partial:
        raise ValueError('Unresolved needs: fill gaps or explicitly export with --allow-partial')
    if not selection.get('selections'):
        raise ValueError('No selections to export')
    fps = project.config['fps']
    width, height = project.config['width'], project.config['height']
    if not isinstance(fps, int) or not 1 <= fps <= 120 or width % 2 or height % 2:
        raise ValueError('MVP requires integer fps 1..120 and even dimensions')
    entries = selection['selections']
    validate_plan({'needs': [e['need'] for e in entries]})
    ends = {'video': 0, 'audio': 0}
    # Validate everything before rendering any asset.
    for e in sorted(entries, key=lambda x: x['timeline_at']):
        if e['kind'] not in ends or not math.isfinite(e['timeline_at']) or e['timeline_at'] < 0:
            raise ValueError('Invalid timeline entry')
        if e['timeline_at'] < ends[e['kind']]-1e-6:
            raise ValueError('MVP supports one non-overlapping video lane and one SFX lane')
        if e.get('provenance', {}).get('provider') in PROVIDERS:
            policy(project, e['provenance'])
        info = probe(e['source_path'])
        if sha(e['source_path']) != e['sha256']:
            raise ValueError('Source changed after selection; reindex and select again')
        if info['kind'] != e['kind'] or not all(math.isfinite(e[k]) for k in ('source_in', 'source_out')) or not 0 <= e['source_in'] < e['source_out'] <= info['duration']+0.001:
            raise ValueError('Source time range or media kind is invalid')
        ends[e['kind']] = e['timeline_at']+e['source_out']-e['source_in']
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Export destination must be empty; existing deliverables were preserved')
    media_dir = destination/'public'/'assets'
    media_dir.mkdir(parents=True, exist_ok=True)
    manifest = {'version': 1, 'fps': fps, 'width': width, 'height': height, 'clips': [], 'unresolved': selection.get('unresolved', [])}
    for e in entries:
        count = max(1, round((e['source_out']-e['source_in'])*fps))
        duration = count/fps
        name = e['need']['id']+('.mp4' if e['kind']=='video' else '.wav')
        target = media_dir/name
        args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', e['source_in'], '-i', e['source_path'], '-t', duration]
        if e['kind']=='video':
            args += ['-map', '0:v:0', '-map', '0:a:0?', '-vf',
                     f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}',
                     '-frames:v', count, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-movflags', '+faststart']
        else:
            args += ['-vn', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le']
        run(args+[target])
        rendered = probe(target)
        if abs(rendered['duration']-duration) > max(0.1, 2/fps):
            raise ValueError('Rendered duration differs from selection')
        manifest['clips'].append({'id': e['need']['id'], 'src': 'assets/'+name, 'absolutePath': str(target),
                                 'kind': e['kind'], 'from': round(e['timeline_at']*fps), 'durationInFrames': count,
                                 'hasAudio': rendered['has_audio'], 'sha256': sha(target), 'source': e})
    manifest['durationInFrames'] = max(c['from']+c['durationInFrames'] for c in manifest['clips'])
    write_json(destination/'manifest.json', manifest)
    write_json(destination/'public'/'manifest.json', manifest)
    write_json(destination/'provenance.json', [c['source'] for c in manifest['clips']])
    credits = ['# 素材来源与署名', '', '本目录为本地剪辑工作文件。平台许可素材不得作为独立素材包、模板源文件或图库对外分发；请按每条许可交付最终创作。', '']
    for c in manifest['clips']:
        e = c['source']; p = e.get('provenance', {})
        if p.get('provider') not in PROVIDERS: continue
        rights = policy(project, p)
        credits += [f'- {c["id"]}: {p.get("title", c["id"])} — {p.get("author", "")}',
                    f'  来源 / Media provided by {p["provider"]}: {p.get("source_page", "")}',
                    f'  许可: {p.get("license_url", "")}',
                    f'  修改: 裁切源 {e["source_in"]}–{e["source_out"]} 秒、尺寸/帧率归一化；最终编辑请补充实际修改。',
                    '  必须在最终发布位置保留署名、来源、许可与修改说明。' if rights['attribution_required'] else '  素材许可不强制署名；检索界面仍保留平台来源。', '']
    (destination/'CREDITS.md').write_text('\n'.join(credits), encoding='utf-8')
    with (destination/'clips.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['id', 'source', 'source_in_seconds', 'source_out_seconds', 'timeline_seconds', 'rendered_file', 'license'])
        for c in manifest['clips']:
            e = c['source']
            writer.writerow([c['id'], e['source_path'], e['source_in'], e['source_out'], e['timeline_at'], c['absolutePath'], e['provenance'].get('license_url', 'local-user-supplied')])
    xml_timeline(manifest, destination/'resolve.xml')
    template = Path(__file__).parent.parent/'examples'/'AssetTimeline.tsx'
    (destination/'AssetTimeline.tsx').write_text(template.read_text(encoding='utf-8'), encoding='utf-8')
    return {'manifest': str(destination/'manifest.json'), 'resolve_xml': str(destination/'resolve.xml'), 'clips': len(manifest['clips'])}
