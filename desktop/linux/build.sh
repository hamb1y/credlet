#!/bin/sh
# Run in the pinned build container, against a separate writable source copy.
set -eu
cd /work
python desktop/build.py --node-only
node_directory=$(mktemp -d)
trap 'rm -rf "$node_directory"' EXIT HUP INT TERM
tar -xJf desktop/build/node-v24.22.1-linux-x64.tar.xz --strip-components=1 -C "$node_directory"
export PATH="$node_directory/bin:$PATH"
npm ci --no-audit --no-fund
python desktop/build.py
python - <<'PY'
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

archive = next(Path('desktop/dist').glob('credlet-desktop-*-linux-x64.tar.gz'))
report = {
    'distribution': Path('/etc/os-release').read_text(),
    'libc': platform.libc_ver(),
    'python': sys.version,
    'node': subprocess.check_output(['node', '--version'], text=True).strip(),
    'baseImage': next(line.removeprefix('FROM ') for line in
        Path('desktop/linux/Dockerfile').read_text().splitlines() if line.startswith('FROM ')),
    'pythonPackages': json.loads(subprocess.check_output(
        [sys.executable, '-m', 'pip', 'list', '--local', '--format=json'], text=True)),
    'packages': subprocess.check_output(['dpkg-query', '-W'], text=True).splitlines(),
    'archive': archive.name,
    'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
}
Path(str(archive) + '.build.json').write_text(json.dumps(report, indent=2) + '\n')
PY
desktop/dist/Credlet/Credlet --check-runtime
