#!/usr/bin/env python3
"""Fetch the isolated Compose test VM runtime without installing host packages.

The pinned Arch binaries were tested on x86_64/glibc 2.44. Python 3.14's
tarfile Zstandard support and bsdtar are required. Existing VM disks are untouched.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
ISO='alpine-virt-3.24.3-x86_64.iso'
ISO_SHA256='cdc1bc0efc64d8d611bf3733f54868172a545888dfd726f518bf279bcb0ff1af'


def fetch(path,urls,digest):
    def verified(file):
        with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()==digest
    if path.is_file() and verified(path):return
    temporary=path.with_suffix(path.suffix+'.partial')
    for url in urls:
        try:
            with urllib.request.urlopen(url,timeout=60) as response,temporary.open('wb') as output:
                while chunk:=response.read(1024*1024):output.write(chunk)
            if not verified(temporary):raise ValueError('Checksum mismatch: '+path.name)
            temporary.replace(path)
            return
        except urllib.error.HTTPError as error:
            if error.code!=404:raise
        finally:temporary.unlink(missing_ok=True)
    raise FileNotFoundError('Pinned runtime unavailable: '+path.name)


def main():
    qemu=ROOT/'.tools/qemu';alpine=ROOT/'.tools/alpine';vm=ROOT/'.tools/linux-vm'
    for directory in (qemu,alpine,vm):directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    for package in json.loads(Path(__file__).with_name('linux-vm-packages.json').read_text()):
        filename=package['FILENAME'];archive=qemu/filename
        fetch(archive,[
            'https://geo.mirror.pkgbuild.com/extra/os/x86_64/'+filename,
            'https://archive.archlinux.org/packages/'+package['NAME'][0]+'/'+package['NAME']+'/'+filename,
        ],package['SHA256SUM'])
        with tarfile.open(archive,mode='r:*') as bundle:
            for member in bundle.getmembers():
                if not member.name.startswith('usr/'):continue
                destination=qemu/'root'/member.name
                if member.isfile() and destination.is_file() and not destination.is_symlink():
                    with destination.open('rb') as current,bundle.extractfile(member) as expected:
                        if hashlib.file_digest(current,'sha256').digest()!=hashlib.file_digest(expected,'sha256').digest():
                            raise RuntimeError('Existing runtime differs; stop its VM and remove .tools/qemu/root before refetching')
                    continue
                if member.issym() and destination.is_symlink() and os.readlink(destination)==member.linkname:continue
                bundle.extract(member,qemu/'root',filter='data')
        print('Verified '+filename,flush=True)
    fetch(alpine/ISO,['https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/'+ISO],ISO_SHA256)
    for name in ('vmlinuz-virt','initramfs-virt'):
        result=subprocess.run(['bsdtar','-xOf',str(alpine/ISO),'boot/'+name],capture_output=True,check=True)
        (vm/name).write_bytes(result.stdout)
    print('Verified Alpine ISO and extracted boot files. No disk was created or formatted.')


if __name__=='__main__':main()
