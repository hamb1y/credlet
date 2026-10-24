#!/usr/bin/env python3
"""Validate versions and assemble an explicit, checksum-verified release asset set."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / 'package.json').read_text())['version']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checksum(path):
    Path(str(path) + '.sha256').write_text(digest(path) + '  ' + path.name + '\n')


def validate():
    if not re.fullmatch(r'\d+\.\d+\.\d+', VERSION):
        raise ValueError('package.json must contain a three-part release version.')
    ref = os.environ.get('GITHUB_REF', '')
    if ref.startswith('refs/tags/') and ref != 'refs/tags/v' + VERSION:
        raise ValueError('The release tag must match package.json: v' + VERSION)
    print('Validated release version ' + VERSION)


def extensions():
    source = ROOT / 'extension/dist'
    output = ROOT / 'dist/extensions'
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for filename in (f'credlet-chrome-{VERSION}.zip', f'credlet-extension-source-{VERSION}.zip',
                     f'credlet-firefox-{VERSION}.xpi'):
        path = source / filename
        expected = Path(str(path) + '.sha256').read_text().split()[0]
        if digest(path) != expected:
            raise ValueError('Extension checksum mismatch: ' + filename)
        destination = output / filename.replace(f'{VERSION}.xpi', f'{VERSION}-unsigned.xpi')
        shutil.copyfile(path, destination)
        checksum(destination)
    signed = list((source / 'signed').glob('*.xpi'))
    if len(signed) > 1:
        raise ValueError('Expected at most one signed Firefox package.')
    if signed:
        with zipfile.ZipFile(signed[0]) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            if manifest['version'] != VERSION or manifest['browser_specific_settings']['gecko']['id'] != 'lockbox@selfhost.local':
                raise ValueError('Signed extension identity/version mismatch.')
            if not {'META-INF/mozilla.rsa', 'META-INF/mozilla.sf'} <= set(archive.namelist()):
                raise ValueError('Mozilla signature files are absent.')
        destination = output / f'credlet-firefox-{VERSION}-signed.xpi'
        shutil.copyfile(signed[0], destination)
        checksum(destination)


def native():
    output = ROOT / 'dist/native'
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    system = 'win' if os.name == 'nt' else 'linux'
    suffix = 'zip' if os.name == 'nt' else 'tar.gz'
    for component in ('desktop', 'server'):
        name = f'credlet-{component}-{VERSION}-{system}-x64.{suffix}'
        for ending in ('', '.sha256', '.build.json'):
            source = ROOT / component / 'dist' / (name + ending)
            shutil.copyfile(source, output / source.name)


def collect(directory, output):
    native = [f'credlet-{component}-{VERSION}-{system}-x64.{suffix}'
        for component in ('desktop', 'server')
        for system, suffix in (('linux', 'tar.gz'), ('win', 'zip'))]
    archives = native + [f'credlet-chrome-{VERSION}.zip',
        f'credlet-firefox-{VERSION}-unsigned.xpi', f'credlet-extension-source-{VERSION}.zip']
    signed = f'credlet-firefox-{VERSION}-signed.xpi'
    if (directory / signed).exists():
        archives.append(signed)
    expected = set(archives + [name + '.sha256' for name in archives] +
                   [name + '.build.json' for name in native])
    actual = {path.name for path in directory.iterdir()}
    if expected != actual:
        raise ValueError(f'Incomplete/unexpected release inputs; missing={expected-actual}, extra={actual-expected}')
    for name in archives:
        path = directory / name
        line = (directory / (name + '.sha256')).read_text().strip()
        if line != digest(path) + '  ' + name:
            raise ValueError('Release checksum mismatch: ' + name)
    for name in native:
        report = json.loads((directory / (name + '.build.json')).read_text())
        if report['sha256'] != digest(directory / name) or report['archive'] != name:
            raise ValueError('Build metadata checksum mismatch: ' + name)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    # Keep convenient per-file checksums as well as the complete signed-tag set.
    for name in sorted(expected):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Release inputs must be regular files.')
        shutil.copyfile(path, output / name)
    report = {'version': VERSION, 'commit': os.environ.get('GITHUB_SHA'),
        'firefoxSigning': 'signed' if signed in archives else 'unsigned',
        'artifacts': [{'file': name, 'bytes': (output / name).stat().st_size,
                       'sha256': digest(output / name)} for name in sorted(expected)]}
    (output / 'release-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    files = sorted(output.iterdir())
    (output / 'SHA256SUMS').write_text(''.join(digest(path) + '  ' + path.name + '\n' for path in files))
    firefox = ('A Mozilla-signed Firefox XPI is included.' if signed in archives else
        'The Firefox XPI is unsigned: use a temporary development installation. Stable Firefox requires Mozilla signing.')
    notes = f'''Credlet {VERSION}

Self-hosted password vault tooling with Windows/Linux x64 desktop apps and server management tools, Chrome and Firefox extensions, and matching extension reviewer sources.

This release renames Lockbox to Credlet, refreshes the browser and native desktop interfaces, and fixes website-rule preservation, asynchronous session locking, empty API responses, and ambiguous password-field filling. Existing native app links, Firefox identity, desktop preferences and server Compose projects remain compatible.

Download the archive for your OS and keep its extracted folder together. Python and Node are bundled; the server tool requires Docker with a Linux container engine and Docker Compose v2. The vault service runs in pinned Vaultwarden/Caddy containers.

{firefox}

macOS releases are deferred. Desktop binaries are not code-signed. Chrome uses Developer mode / Load unpacked; this is not a Chrome Web Store release.

Verify downloads with SHA256SUMS. Build metadata and a release-manifest.json accompany the archives.

- [Upgrading from Lockbox](https://github.com/hamb1y/credlet/blob/v{VERSION}/docs/upgrading.md)
- [Setup and recovery](https://github.com/hamb1y/credlet/blob/v{VERSION}/docs/self-hosting.md)
- [Desktop usage](https://github.com/hamb1y/credlet/blob/v{VERSION}/desktop/README.md)
- [Extension installation](https://github.com/hamb1y/credlet/blob/v{VERSION}/extension/README.md)

First-party code: MIT. Third-party licenses accompany each bundle.
'''
    (ROOT / 'dist/release-notes.md').write_text(notes)
    print(f'Collected {len(archives)} archives for {VERSION}; Firefox: {report["firefoxSigning"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('validate')
    subs.add_parser('extensions')
    subs.add_parser('native')
    collect_parser = subs.add_parser('collect')
    collect_parser.add_argument('--input', type=Path, default=ROOT / 'dist/downloaded')
    collect_parser.add_argument('--output', type=Path, default=ROOT / 'dist/release')
    args = parser.parse_args()
    validate()
    if args.command == 'extensions':
        extensions()
    elif args.command == 'native':
        native()
    elif args.command == 'collect':
        collect(args.input, args.output)


if __name__ == '__main__':
    main()
