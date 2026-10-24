#!/usr/bin/env python3
"""Freeze the deployment/control CLI on its target OS; Docker runs the services."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from bundle_licenses import bundle_licenses

ROOT = Path(__file__).resolve().parents[1]


def main():
    system = {'linux': 'linux', 'win32': 'win'}.get(sys.platform)
    if system is None or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('Server releases currently target Windows/Linux x64.')
    build = ROOT / 'server/build'
    output = ROOT / 'server/dist'
    build.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--onedir', '--noupx', '--name', 'credlet-server', '--distpath', str(output),
        '--workpath', str(build / 'pyinstaller'), '--specpath', str(build),
        str(ROOT / 'credlet.py')], cwd=ROOT, check=True)
    folder = output / 'credlet-server'
    bundle_licenses(folder)
    shutil.copyfile(ROOT / 'docs/self-hosting.md', folder / 'README.md')
    version = json.loads((ROOT / 'package.json').read_text())['version']
    stem = f'credlet-server-{version}-{system}-x64'
    archive = Path(shutil.make_archive(str(output / stem),
        'zip' if system == 'win' else 'gztar', root_dir=output, base_dir=folder.name))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(str(archive) + '.sha256').write_text(digest + '  ' + archive.name + '\n')
    report = {'version': version, 'platform': system, 'architecture': 'x64',
        'python': sys.version, 'libc': platform.libc_ver(), 'archive': archive.name,
        'sha256': digest, 'purpose': 'Docker Compose deployment/control CLI'}
    Path(str(archive) + '.build.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Built ' + str(archive), flush=True)


if __name__ == '__main__':
    main()
