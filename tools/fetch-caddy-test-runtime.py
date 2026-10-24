#!/usr/bin/env python3
"""Extract the pinned Caddy test executable from digest-verified OCI image layers."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import credlet
root=credlet.ROOT/'.tools';root.mkdir(exist_ok=True,mode=0o700)
repo='library/caddy'
with urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:'+repo+':pull',timeout=30) as r:
    token=json.load(r)['token']
def fetch(kind,digest):
    req=urllib.request.Request('https://registry-1.docker.io/v2/'+repo+'/'+kind+'/'+digest,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json'})
    with urllib.request.urlopen(req,timeout=90) as r:content=r.read()
    if 'sha256:'+hashlib.sha256(content).hexdigest()!=digest:raise ValueError('OCI digest verification failed')
    return content
index=json.loads(fetch('manifests',credlet.CADDY_IMAGE.split('@')[1]))
manifest=next(m['digest'] for m in index['manifests'] if m['platform'].get('architecture')=='amd64' and m['platform'].get('os')=='linux')
image=json.loads(fetch('manifests',manifest))
found=False
for layer in image['layers']:
    content=fetch('blobs',layer['digest'])
    with tarfile.open(fileobj=io.BytesIO(content),mode='r:*') as archive:
        for m in archive.getmembers():
            if m.name.removeprefix('./')=='usr/bin/caddy' and m.isfile():
                (root/'caddy').write_bytes(archive.extractfile(m).read());(root/'caddy').chmod(0o755);found=True
    print('Verified Caddy layer:',layer['digest'],flush=True)
if not found:raise RuntimeError('Image did not contain Caddy executable')
print('Verified Caddy executable in',root/'caddy')
