#!/usr/bin/env python3
"""Portable entrypoint, independent of shell cwd or package installation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asset_discovery.cli import main
raise SystemExit(main())
