#!/usr/bin/env python3
"""Wait for the frozen desktop runtime check, including Windows GUI executables."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='lockbox desktop smoke ') as temporary:
    report = Path(temporary) / 'runtime.json'
    subprocess.run([str(Path(sys.argv[1]).resolve()), '--check-runtime', '--report', str(report)],
                   check=True, timeout=90)
    data = json.loads(report.read_text())
    assert data['ok'] and data['bundled'] and data['vaultLocked'], data
    print('PASS frozen desktop runtime: ' + json.dumps(data))
