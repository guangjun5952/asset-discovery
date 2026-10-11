#!/usr/bin/env python3
"""Render an exported manifest with FFmpeg (one V lane + one SFX lane)."""
import argparse
import json
import subprocess
from pathlib import Path


def render(manifest_path, target):
    manifest_path = Path(manifest_path).resolve()
    m = json.loads(manifest_path.read_text(encoding='utf-8'))
    fps, duration = m['fps'], m['durationInFrames']/m['fps']
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-f', 'lavfi', '-i',
            f'color=c=black:s={m["width"]}x{m["height"]}:r={fps}:d={duration}']
    for c in m['clips']:
        # Use portable public/ path; JSON original absolutePath is audit-only here.
        path = (manifest_path.parent/'public'/c['src']).resolve()
        if not path.is_relative_to(manifest_path.parent/'public'):
            raise ValueError('Manifest asset must stay inside public/')
        args += ['-i', str(path)]
    filters, previous, sounds = [], '0:v', []
    for i, c in enumerate(m['clips'], 1):
        at = c['from']/fps
        end = (c['from']+c['durationInFrames'])/fps
        if c['kind']=='video':
            filters.append(f'[{i}:v]setpts=PTS-STARTPTS+{at}/TB[v{i}]')
            filters.append(f'[{previous}][v{i}]overlay=eof_action=pass:enable=\'between(t,{at},{end})\'[out{i}]')
            previous = f'out{i}'
        if c['hasAudio']:
            filters.append(f'[{i}:a]adelay={round(at*1000)}:all=1[a{i}]')
            sounds.append(f'[a{i}]')
    filters.append(f'[{previous}]null[video]')
    if sounds:
        filters.append(''.join(sounds)+f'amix=inputs={len(sounds)}:normalize=0,alimiter=limit=0.95[audio]')
    args += ['-filter_complex', ';'.join(filters), '-map', '[video]']
    if sounds:
        args += ['-map', '[audio]', '-c:a', 'aac']
    args += ['-t', str(duration), '-r', str(fps), '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)]
    subprocess.run(args, check=True)

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest'); parser.add_argument('output')
    a = parser.parse_args()
    render(a.manifest, a.output)
