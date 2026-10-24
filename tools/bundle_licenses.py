"""Copy first-party and installed runtime notices into native distributions."""
import importlib.metadata
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def bundle_licenses(folder):
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT / name, folder / name)
    output = folder / 'third-party-licenses'
    output.mkdir(exist_ok=True)
    python_licenses = [Path(sys.base_prefix) / 'LICENSE.txt']
    if sys.platform == 'linux':
        # Debian copyright documents include full license texts, including those
        # for the dynamically linked GUI libraries collected by PyInstaller.
        for path in sorted(Path('/usr/share/doc').glob('*/copyright')):
            if path.is_file():
                shutil.copyfile(path, output / (path.parent.name + '-copyright.txt'))
        python_licenses.extend(Path('/usr/share/doc').glob('libpython*/copyright'))
    python_licenses = [path for path in python_licenses if path.is_file()]
    if not python_licenses:
        raise RuntimeError('Cannot find the bundled Python interpreter license.')
    shutil.copyfile(python_licenses[0], output / 'PYTHON_LICENSE.txt')
    for name in ('pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph', 'packaging', 'comtypes'):
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        for relative in distribution.files or ():
            if relative.name.lower().startswith(('license', 'copying')):
                source = distribution.locate_file(relative)
                if source.is_file():
                    shutil.copyfile(source, output / (name + '-' + relative.name))
    for path in (Path(sys.base_prefix) / 'tcl').glob('*/license.terms'):
        shutil.copyfile(path, output / (path.parent.name + '-license.terms'))
