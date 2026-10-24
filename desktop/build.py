#!/usr/bin/env python3
"""Build a self-contained desktop bundle on its target OS. Requires PyInstaller and npm ci."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from bundle_licenses import bundle_licenses

NODE_VERSION = '24.22.1'
ROOT = Path(__file__).resolve().parents[1]


def node_runtime(directory):
    system={'linux':'linux','darwin':'darwin','win32':'win'}.get(sys.platform)
    architecture={'x86_64':'x64','amd64':'x64','aarch64':'arm64','arm64':'arm64'}.get(platform.machine().lower())
    if not system or not architecture:raise RuntimeError('Build on Linux, Windows or macOS, on x64 or arm64.')
    stem=f'node-v{NODE_VERSION}-{system}-{architecture}'
    filename=stem+('.zip' if system=='win' else '.tar.xz')
    base=f'https://nodejs.org/dist/v{NODE_VERSION}/'
    checksums=urllib.request.urlopen(base+'SHASUMS256.txt',timeout=60).read().decode()
    expected=next(line.split()[0] for line in checksums.splitlines() if line.split()[-1]==filename)
    archive=directory/filename
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:
        temporary=archive.with_suffix('.download')
        with urllib.request.urlopen(base+filename,timeout=60) as source,temporary.open('wb') as target:shutil.copyfileobj(source,target)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:
            temporary.unlink();raise RuntimeError('Node runtime checksum mismatch.')
        temporary.replace(archive)
    destination=directory/'runtime';destination.mkdir(exist_ok=True)
    if system=='win':
        with zipfile.ZipFile(archive) as bundle:
            node=bundle.read(stem+'/node.exe');license=bundle.read(stem+'/LICENSE')
    else:
        with tarfile.open(archive) as bundle:
            node=bundle.extractfile(stem+'/bin/node').read();license=bundle.extractfile(stem+'/LICENSE').read()
    executable=destination/('node.exe' if system=='win' else 'node')
    executable.write_bytes(node);executable.chmod(0o755)
    (destination/'NODE_LICENSE.txt').write_bytes(license)
    metadata={'version':NODE_VERSION,'platform':system,'architecture':architecture,'archive':filename,'sha256':expected}
    (destination/'node-runtime.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return executable,metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node-only',action='store_true',help='Fetch and verify the runtime without building the UI.')
    args=parser.parse_args()
    output=ROOT/'desktop/build';output.mkdir(parents=True,exist_ok=True)
    node,metadata=node_runtime(output)
    print('Verified Node runtime: '+json.dumps(metadata),flush=True)
    if args.node_only:return
    # Fail before packaging if the chosen Python lacks the actual platform dependencies.
    import tkinter
    if sys.platform=='linux':
        import gi
        gi.require_version('Atspi','2.0')
        from gi.repository import Atspi
    elif sys.platform=='win32':import comtypes.client
    elif sys.platform=='darwin':import ApplicationServices,AppKit
    subprocess.run([str(node),str(ROOT/'desktop/build.mjs')],cwd=ROOT,check=True)
    # PyInstaller 6 accepts a colon on all platforms, including Windows drive paths.
    separator=':'
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--noupx',
        '--name','Credlet','--paths',str(ROOT),'--distpath',str(ROOT/'desktop/dist'),
        '--workpath',str(output/'pyinstaller'),'--specpath',str(output),'--additional-hooks-dir',str(ROOT/'desktop/hooks'),
        '--add-data',str(output/'runtime')+separator+'runtime',str(ROOT/'desktop/app.py')]
    if sys.platform=='linux':command.extend(['--hidden-import','gi.repository.Atspi','--hidden-import','gi.repository.GLib'])
    if sys.platform in ('darwin','win32'):command.append('--windowed')
    if sys.platform=='win32':command.extend(['--collect-submodules','comtypes'])
    if sys.platform=='darwin':
        # Stage resources before PyInstaller seals the .app. Adding a README
        # afterward would invalidate its ad-hoc or distribution signature.
        command.extend(['--osx-bundle-identifier','local.credlet.desktop',
            '--add-data',str(ROOT/'desktop/README.md')+separator+'.'])
    subprocess.run(command,cwd=ROOT,check=True)
    distribution=ROOT/'desktop/dist'
    version=json.loads((ROOT/'package.json').read_text())['version']
    name=f'credlet-desktop-{version}-{metadata["platform"]}-{metadata["architecture"]}'
    folder=distribution/('Credlet.app' if sys.platform=='darwin' else 'Credlet')
    if sys.platform=='darwin':
        subprocess.run(['codesign','--verify','--deep','--strict',str(folder)],check=True)
    else:
        shutil.copyfile(ROOT/'desktop/README.md',folder/'README.md')
        bundle_licenses(folder)
    archive=shutil.make_archive(str(distribution/name),'zip' if sys.platform=='win32' else 'gztar',root_dir=distribution,base_dir=folder.name)
    digest=hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    Path(archive+'.sha256').write_text(digest+'  '+Path(archive).name+'\n')
    report={'version':version,'platform':metadata['platform'],'architecture':metadata['architecture'],
        'python':sys.version,'node':metadata,'archive':Path(archive).name,'sha256':digest}
    Path(archive+'.build.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Built '+archive,flush=True)


if __name__=='__main__':main()
