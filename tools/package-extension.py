#!/usr/bin/env python3
"""Package built extension targets and matching reviewer sources deterministically."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILT_FILES = frozenset(('manifest.json', 'background.js', 'content.js', 'ui.js',
    'passkey-page.js', 'passkey-bridge.js', 'vault.html', 'vault.css', 'THIRD_PARTY_LICENSES.txt'))
SOURCE_FILES = ('package.json', 'package-lock.json', 'extension/build.mjs',
    'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'desktop/bridge.mjs', 'tests/verify_passkeys.mjs', 'tools/package-extension.py',
    'lockbox.py', 'extension/release/README.md', 'extension/release/privacy.md',
    'extension/release/amo-metadata.json')


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Expected a regular release input: ' + str(path.relative_to(ROOT)))
    return path


def write_archive(destination, files):
    # Explicit inputs keep vault state, credentials and unrelated build output
    # out of a signing upload. Fix timestamps and modes across host OSes.
    temporary = Path(str(destination) + '.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, path in sorted(files):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                bundle.writestr(info, regular(path).read_bytes())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    Path(str(destination) + '.sha256').write_text(digest + '  ' + destination.name + '\n')
    print(destination)
    return {'file': destination.name, 'size': destination.stat().st_size, 'sha256': digest}


def main():
    version = json.loads((ROOT / 'package.json').read_text())['version']
    output = ROOT / 'extension/dist'
    inputs = []
    for target, suffix in (('firefox', 'xpi'), ('chrome', 'zip')):
        directory = output / target
        if not directory.is_dir():
            raise RuntimeError('Run npm ci and npm run build first.')
        if {path.name for path in directory.iterdir()} != BUILT_FILES:
            raise RuntimeError('Unexpected or missing files in ' + str(directory.relative_to(ROOT)) + '; rebuild first.')
        files = [(name, regular(directory / name)) for name in BUILT_FILES]
        manifest = json.loads((directory / 'manifest.json').read_text())
        if manifest['version'] != version:
            raise RuntimeError('The built manifest version differs from package.json; rebuild first.')
        inputs.append((output / f'lockbox-{target}-{version}.{suffix}', files))
    sources = [(name, regular(ROOT / name)) for name in SOURCE_FILES]
    self_hosting = ROOT / 'SELF_HOSTING.md'
    if not self_hosting.exists():self_hosting = ROOT / 'docs/self-hosting.md'
    sources.extend((('README.md', ROOT / 'extension/release/README.md'), ('SELF_HOSTING.md', regular(self_hosting))))
    for directory, suffixes in (('extension/src', {'.js', '.css', '.html'}), ('extension/test', {'.mjs'})):
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_symlink():
                raise RuntimeError('Symlinks are not release sources.')
            if path.is_file() and path.suffix in suffixes and not path.name.startswith('.'):
                sources.append((path.relative_to(ROOT).as_posix(), regular(path)))
    inputs.append((output / f'lockbox-extension-source-{version}.zip', sources))
    artifacts = [write_archive(destination, files) for destination, files in inputs]
    report = {'version': version, 'firefoxSigning': 'unsigned', 'artifacts': artifacts}
    (output / 'release.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
