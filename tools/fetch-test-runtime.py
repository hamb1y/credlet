#!/usr/bin/env python3
"""Fetch pinned Linux x86_64 test binaries from the Vaultwarden OCI image.
No container daemon required. Downloaded content stays in ignored .tools/.
"""
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lockbox

root = lockbox.ROOT / '.tools'
root.mkdir(exist_ok=True, mode=0o700)
repo = 'dani-garcia/vaultwarden'
token = json.load(urllib.request.urlopen('https://ghcr.io/token?scope=repository:' + repo + ':pull'))['token']


def fetch(kind, digest):
    request = urllib.request.Request('https://ghcr.io/v2/' + repo + '/' + kind + '/' + digest,
        headers={'Authorization':'Bearer ' + token,
                 'Accept':'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        content = response.read()
    if 'sha256:' + hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('OCI digest verification failed')
    return content


index = json.loads(fetch('manifests', lockbox.VW_IMAGE.split('@')[1]))
manifest_digest = next(m['digest'] for m in index['manifests'] if m['platform'] == {'architecture':'amd64', 'os':'linux'})
manifest = json.loads(fetch('manifests', manifest_digest))
for layer in manifest['layers']:
    print('Verifying layer:', layer['digest'], flush=True)
    content = fetch('blobs', layer['digest'])
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:*') as archive:
        for member in archive.getmembers():
            name = member.name.removeprefix('./')
            if name in ('vaultwarden', 'healthcheck.sh') or name.startswith(('web-vault/', 'usr/lib/x86_64-linux-gnu/')):
                archive.extract(member, root, filter='data')
(root / 'lib').mkdir(exist_ok=True)
for name in ('libmariadb.so.3', 'libpq.so.5'):
    shutil.copyfile(root / 'usr/lib/x86_64-linux-gnu' / name, root / 'lib' / name)
print('Verified test runtime in', root)
