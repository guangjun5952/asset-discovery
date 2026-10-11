#!/usr/bin/env python3
"""Install without touching unrelated skills. Existing target is never overwritten."""
import argparse
import shutil
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--target', choices=['codex', 'claude'], default='codex')
p.add_argument('--destination', help='Optional explicit skills parent directory')
a = p.parse_args()
source = Path(__file__).resolve().parents[1]
parent = Path(a.destination).expanduser() if a.destination else Path.home()/('.codex' if a.target=='codex' else '.claude')/'skills'
target = parent/'asset-discovery'
if target.exists():
    raise SystemExit(f'Already exists; preserved: {target}')
parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', '.git', '.github', '.venv', '.env', '.env.*', 'asset-project', 'asset-demo', 'my-project', 'delivery'))
print(target)
