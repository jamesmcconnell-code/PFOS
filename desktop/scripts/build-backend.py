"""Build on the target OS/architecture using the project's Python 3.12 pins."""
import json
import os
from pathlib import Path
import platform
import sys

if sys.version_info[:2] != (3, 12):
    raise SystemExit('Build with Python 3.12. Set PFOS_BUILD_PYTHON to that interpreter.')

root = Path(__file__).resolve().parents[1]
os.environ['PYINSTALLER_CONFIG_DIR'] = str(root / '.build' / 'pyinstaller-cache')
from PyInstaller.__main__ import run
run(['--noconfirm', '--clean', '--distpath', str(root / 'resources' / 'backend'),
     '--workpath', str(root / '.build' / 'backend'), str(root / 'backend.spec')])
(root / 'resources' / 'backend' / 'build-info.json').write_text(json.dumps({
    'python': platform.python_version(), 'platform': sys.platform,
    'architecture': platform.machine(),
}, indent=2) + '\n')
