#!/usr/bin/env python3
"""Rebuild reviewer sources in a clean directory and compare all three archives."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    version = json.loads((ROOT / 'package.json').read_text())['version']
    names = [f'lockbox-chrome-{version}.zip', f'lockbox-firefox-{version}.xpi',
             f'lockbox-extension-source-{version}.zip']
    npm = shutil.which('npm')
    with tempfile.TemporaryDirectory(prefix='lockbox clean reviewer rebuild ') as temporary:
        directory = Path(temporary)
        with zipfile.ZipFile(ROOT / 'extension/dist' / names[-1]) as archive:
            archive.extractall(directory)
        for arguments in (['ci', '--no-audit', '--no-fund'], ['test'], ['run', 'build']):
            subprocess.run([npm, *arguments], cwd=directory, check=True)
        subprocess.run([sys.executable, 'tools/package-extension.py'], cwd=directory, check=True)
        for name in names:
            if (ROOT / 'extension/dist' / name).read_bytes() != (directory / 'extension/dist' / name).read_bytes():
                raise RuntimeError('Reviewer rebuild differs: ' + name)
    print('PASS byte-identical Firefox, Chrome and reviewer-source archives')


if __name__ == '__main__':
    main()
