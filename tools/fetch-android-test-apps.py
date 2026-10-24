#!/usr/bin/env python3
"""Fetch pinned official APKs into the disposable Android acceptance workspace."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]/'.tools/android-apps'
APPS=[
    ('bitwarden-2026.10.0.apk','https://github.com/bitwarden/android/releases/download/v2026.10.0-bwpm/com.x8bit.bitwarden-fdroid.apk',
        '63a1072029253e8b2e017e52aa49b0a70dba05a433239f211a64aa2206fadb64',True),
    ('firefox-nightly-161.apk','https://archive.mozilla.org/pub/fenix/nightly/2026/10/2026-10-23-09-50-57-fenix-161.0a1-android-x86_64/fenix-161.0a1.multi.android-x86_64.apk',
        '865f4b23fc83713402451ba119f19aede696aaf318f64b68dd3371f8a2ed671a',False),
]


def fetch(app):
    name,url,expected,upstream=app;target=ROOT/name
    def checksum(path):
        with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()
    if not target.exists() or checksum(target)!=expected:
        temporary=target.with_suffix('.download')
        with urllib.request.urlopen(url,timeout=90) as source,temporary.open('wb') as output:
            while chunk:=source.read(1024*1024):output.write(chunk)
        if checksum(temporary)!=expected:
            temporary.unlink();raise RuntimeError('APK checksum mismatch: '+name)
        temporary.replace(target)
    print('Verified '+name,flush=True)
    return {'file':name,'url':url,'sha256':expected,'upstreamChecksumVerified':upstream}


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:report=list(pool.map(fetch,APPS))
    (ROOT/'downloads.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
