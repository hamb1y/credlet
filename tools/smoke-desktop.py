#!/usr/bin/env python3
"""Wait for the frozen desktop runtime check, including Windows GUI executables."""
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='credlet desktop smoke ') as temporary:
    report = Path(temporary) / 'runtime.json'
    command = [str(Path(sys.argv[1]).resolve()), '--check-runtime', '--check-ui', '--report', str(report)]
    if sys.platform == 'linux':
        command = [shutil.which('xvfb-run') or 'xvfb-run', '-a', '--server-args=-screen 0 1280x1024x24 -nolisten tcp', *command]
    subprocess.run(command,
                   check=True, timeout=90)
    data = json.loads(report.read_text())
    assert data['ok'] and data['bundled'] and data['vaultLocked'] and data['ui'], data
    print('PASS frozen desktop runtime and offline UI: ' + json.dumps(data))
