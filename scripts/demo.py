#!/usr/bin/env python3
"""Create copyright-free generated fixtures, index them, produce a review packet. No network."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asset_discovery.core import Project, run, write_json
from asset_discovery.media import index
from asset_discovery.exporting import review_packet

root = Path(sys.argv[1] if len(sys.argv)>1 else './asset-demo').resolve()
if root.exists() and any(root.iterdir()):
    raise SystemExit('Use a new empty demo folder')
media = root/'media'; media.mkdir(parents=True, exist_ok=True)
run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=5',
     '-c:v', 'libx264', '-pix_fmt', 'yuv420p', media/'color-pattern.mp4'])
run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=black:size=1280x720:rate=30:duration=5',
     '-c:v', 'libx264', '-pix_fmt', 'yuv420p', media/'black-reject.mp4'])
run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2', media/'test-tone.wav'])
for filename, description in [('color-pattern.mp4','彩色显示测试图案 color pattern'), ('black-reject.mp4','黑色视频 black frame'), ('test-tone.wav','测试提示音 sine test tone')]:
    write_json(str(media/filename)+'.asset.json', {'description': description, 'rights': 'generated_test_fixture', 'tags': ['synthetic', 'test']})
p = Project.init(root/'project')
p.config.update(roots=[str(media)], width=1280, height=720)
write_json(p.path/'config.json', p.config)
print(index(p))
write_json(p.path/'plan.json', {'method': 'explicit_test_fixture_plan', 'needs': [
    {'id': 'pattern', 'query': '彩色显示图案 pattern', 'kind': 'video', 'route': 'local_only', 'at': 0, 'duration': 4, 'real_only': False},
    {'id': 'tone', 'query': '测试提示音 tone', 'kind': 'audio', 'route': 'local_only', 'at': 1, 'duration': 1, 'real_only': False}]})
print(review_packet(p, root/'review'))
p.db.close()
print('Fill review/review-template.json after viewing/listening, import-review, assemble, then export. No reviews have been fabricated.')
