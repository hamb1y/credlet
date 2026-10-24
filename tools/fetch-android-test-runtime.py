#!/usr/bin/env python3
"""Fetch isolated Linux x64 Android acceptance tools from Google's SDK repository.

Upstream repository XML publishes SHA-1; pins below were read from its stable channel.
Archives remain in .tools and are not part of Credlet's distribution.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]/'.tools'
PACKAGES=[
    ('emulator-linux_x64-16428233.zip','cd7362ea55dfb86a418958138dc396e74165dd01','', 'emulator 37.2.12'),
    ('platform-tools_r37.0.1-linux.zip','477254aa5f903c15cf51001717bdf347fb6b53e0','', 'platform-tools 37.0.1'),
    ('build-tools_r35_linux.zip','2cfaa0bbb2336e9ec18ed3ecea84fa2e2af607bc','build-tools/35.0.0', 'build-tools 35.0.0'),
    ('platform-35_r02.zip','0bb560a90a7a2cbd0dd8348224d518b638fe7949','platforms/android-35', 'platform API 35 r2'),
    ('sys-img/android/x86_64-35_r02.zip','2d857d170c0d1b827149565da34b3383e5306f7f','system-images/android-35/default', 'AOSP API 35 x86_64 r2'),
]
GOOGLE_APIS=('sys-img/google_apis/x86_64-35_r09.zip','0103e6dab21290c4b9d16550a3ce99476f884eef',
    'system-images/android-35/google_apis','Google APIs API 35 x86_64 r9')


def fetch(package):
    remote,expected,subdirectory,version=package
    cache=ROOT/'android-downloads';cache.mkdir(parents=True,exist_ok=True)
    archive=cache/Path(remote).name
    def checksum(path,algorithm):
        with path.open('rb') as source:return hashlib.file_digest(source,algorithm).hexdigest()
    if not archive.exists() or checksum(archive,'sha1')!=expected:
        temporary=archive.with_suffix('.download')
        with urllib.request.urlopen('https://dl.google.com/android/repository/'+remote,timeout=90) as source,temporary.open('wb') as target:
            while chunk:=source.read(1024*1024):target.write(chunk)
        if checksum(temporary,'sha1')!=expected:
            temporary.unlink();raise RuntimeError('Android archive checksum mismatch: '+remote)
        temporary.replace(archive)
    destination=ROOT/'android-sdk'/subdirectory;destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path=PurePosixPath(member.filename)
            if path.is_absolute() or '..' in path.parts or stat.S_ISLNK(member.external_attr>>16):raise RuntimeError('Unsafe SDK archive path.')
            parts=path.parts
            # Build/platform archives contain a single root directory; name it by SDK package.
            if remote.startswith('build-tools') or remote=='platform-35_r02.zip':parts=parts[1:]
            if not parts:continue
            target=destination.joinpath(*parts)
            if member.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with bundle.open(member) as source,target.open('wb') as output:
                while chunk:=source.read(1024*1024):output.write(chunk)
            permissions=(member.external_attr>>16)&0o777
            if permissions:target.chmod(permissions)
    result={'version':version,'archive':remote,'sha1':expected,'sha256':checksum(archive,'sha256')}
    print('Verified/extracted '+version,flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--google-apis',action='store_true',help='Fetch only the optional Google APIs image; keep installed/running tools unchanged.')
    args=parser.parse_args()
    ROOT.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:report=list(pool.map(fetch,[GOOGLE_APIS] if args.google_apis else PACKAGES))
    (ROOT/('android-sdk/google-apis-checksums.json' if args.google_apis else 'android-sdk/runtime-checksums.json')).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
