#!/usr/bin/env python3
"""Single-user Vaultwarden deployment and recovery. Python 3.11+, Docker Compose v2."""
import argparse
import contextlib
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

ROOT = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
VW_IMAGE = 'ghcr.io/dani-garcia/vaultwarden:1.37.4@sha256:efb3cde962015fcc036b2ea625242248611943b27212ebf4392841fb30fad055'
CADDY_IMAGE = 'caddy:2.11.7@sha256:504a44d7d74bd2bc28a66afc4774912fc21223ca8a67734af1c54ab2f999b489'


def private_directory(root):
    """Protect state before writing secrets; chmod alone does not set Windows ACLs."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        root.chmod(0o700)
        return
    script = '''$ErrorActionPreference = 'Stop'
$path = $env:LOCKBOX_PRIVATE_DIRECTORY
$owner = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetOwner($owner)
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in @($owner, [System.Security.Principal.SecurityIdentifier]'S-1-5-18')) {
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $path -AclObject $acl
'''
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script],
                   env={**os.environ, 'LOCKBOX_PRIVATE_DIRECTORY': str(root)}, check=True,
                   capture_output=True, text=True)


@contextlib.contextmanager
def state_lock(root):
    """Serialize lifecycle commands on both Windows and POSIX hosts."""
    with (root / '.lock').open('a+b') as lock:
        if os.name == 'nt':
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b'\0')
                lock.flush()
            while True:
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in (13, 36):
                        raise
                    time.sleep(0.1)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def bind(source, target, readonly=False):
    return {'type': 'bind', 'source': str(source), 'target': target, 'read_only': readonly}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def validate_identity(hostname, email):
    if not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', hostname):
        raise ValueError('Use a DNS hostname, without scheme, port or path.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('A valid owner email is required.')


def init(root, hostname, email):
    validate_identity(hostname, email)
    if (root / 'config.json').exists():
        raise ValueError('Already initialized; configuration was preserved.')
    private_directory(root)
    for name in ('data', 'backups', 'caddy-data', 'caddy-config'):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    write_json(root / 'config.json', {'hostname': hostname, 'owner': email.lower()})
    render(root)


def render(root):
    cfg = json.loads((root / 'config.json').read_text())
    validate_identity(cfg['hostname'], cfg['owner'])
    base = {
        'image': VW_IMAGE, 'restart': 'unless-stopped',
        'volumes': [bind(root / 'data', '/data')],
        'environment': {'DOMAIN': 'https://' + cfg['hostname'], 'SIGNUPS_ALLOWED': 'false',
            'INVITATIONS_ALLOWED': 'false', 'ORG_CREATION_USERS': 'none',
            'SENDS_ALLOWED': 'false', 'SHOW_PASSWORD_HINT': 'false',
            'ROCKET_PORT': '8080', 'ROCKET_ADDRESS': '0.0.0.0',
            'LOGIN_RATELIMIT_MAX_BURST': '5', 'LOGIN_RATELIMIT_SECONDS': '60'},
        'security_opt': ['no-new-privileges:true'], 'cap_drop': ['ALL'],
        'healthcheck': {'test': ['CMD', '/healthcheck.sh'], 'interval': '30s', 'timeout': '5s', 'retries': 3}}
    services = {'vault': base, 'https': {'image': CADDY_IMAGE, 'restart': 'unless-stopped',
        'ports': ['80:80', '443:443', '443:443/udp'],
        'volumes': [bind(root / 'Caddyfile', '/etc/caddy/Caddyfile', True),
            bind(root / 'caddy-data', '/data'), bind(root / 'caddy-config', '/config')],
        'depends_on': {'vault': {'condition': 'service_healthy'}},
        'security_opt': ['no-new-privileges:true']}}
    write_json(root / 'compose.json', {'name': 'lockbox', 'services': services})
    bootstrap = json.loads(json.dumps(base))
    bootstrap['restart'] = 'no'
    bootstrap['ports'] = ['127.0.0.1:8222:8080']
    bootstrap['environment'].update(DOMAIN='http://localhost:8222', SIGNUPS_ALLOWED='true')
    write_json(root / 'enroll.json', {'name': 'lockbox-enroll', 'services': {'vault': bootstrap}})
    (root / 'Caddyfile').write_text(f'''{cfg['hostname']} {{
    encode zstd gzip
    header Strict-Transport-Security "max-age=31536000"
    @admin path /admin /admin/*
    respond @admin 404
    reverse_proxy vault:8080
}}
''')


def compose(root, enrollment, *args, capture=False):
    return subprocess.run(['docker', 'compose', '-f', str(root / ('enroll.json' if enrollment else 'compose.json')), *args],
                          check=True, text=True, capture_output=capture)


def owners(root):
    db = root / 'data/db.sqlite3'
    if not db.is_file():
        return []
    with contextlib.closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as conn:
        return [row[0].lower() for row in conn.execute('SELECT email FROM users')]


def check_owner(root):
    expected = json.loads((root / 'config.json').read_text())['owner']
    if owners(root) != [expected]:
        raise ValueError('Expected exactly one account matching the configured owner. Finish enrollment first.')
    if (root / 'data/config.json').exists():
        raise ValueError('data/config.json can override security settings. Remove it after reviewing its contents.')


def stopped(root):
    # A fresh restore has no Compose files yet. Query the fixed project labels
    # directly, including a deployment started from another state directory.
    for project in ('lockbox-enroll', 'lockbox'):
        running = subprocess.run(['docker', 'ps', '--quiet', '--filter',
            'label=com.docker.compose.project=' + project], check=True, text=True, capture_output=True)
        if running.stdout.strip():
            raise ValueError('Stop both stacks before this operation (lockbox.py down).')


def backup(root):
    """Caller must stop both stacks to snapshot SQLite, keys and attachments together."""
    check_owner(root)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    target = root / 'backups' / f'lockbox-{stamp}.tar.gz'
    with contextlib.closing(sqlite3.connect((root / 'data/db.sqlite3').as_uri() + '?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed.')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
            archive.add(root / 'data', arcname='data')
            archive.add(root / 'config.json', arcname='config.json')
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def restore(root, archive_path):
    if (root / 'data').exists() and any((root / 'data').iterdir()):
        raise ValueError('Restore requires an empty data directory. Move the existing data aside first.')
    private_directory(root)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        stage = Path(tmp)
        with tarfile.open(archive_path, 'r:gz') as archive:
            members = archive.getmembers()
            for member in members:
                parts = Path(member.name).parts
                if not parts or parts[0] not in ('data', 'config.json') or member.name.startswith('/') or '..' in parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Invalid or unsafe backup member.')
            archive.extractall(stage, members=members, filter='data')
        cfg = json.loads((stage / 'config.json').read_text())
        if not isinstance(cfg.get('hostname'), str) or not isinstance(cfg.get('owner'), str):
            raise ValueError('Invalid backup configuration.')
        validate_identity(cfg['hostname'], cfg['owner'])
        check_owner(stage)
        with contextlib.closing(sqlite3.connect((stage / 'data/db.sqlite3').as_uri() + '?mode=ro', uri=True)) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup database failed integrity check.')
        if (root / 'data').exists():
            (root / 'data').rmdir()
        shutil.move(str(stage / 'data'), root / 'data')
        shutil.copyfile(stage / 'config.json', root / 'config.json')
        (root / 'config.json').chmod(0o600)
    for name in ('backups', 'caddy-data', 'caddy-config'):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    render(root)


def probe(root):
    cfg = json.loads((root / 'config.json').read_text())
    origin = 'https://' + cfg['hostname']
    with urllib.request.urlopen(origin + '/api/config', timeout=15) as response:
        data = json.load(response)
    if data.get('object') != 'config':
        raise ValueError('Unexpected service configuration response.')
    with urllib.request.urlopen(origin + '/alive', timeout=15) as response:
        if response.status != 200:
            raise ValueError('Service health endpoint failed.')
    print('HTTPS certificate and service API verified:', origin)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=ROOT / 'state')
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('init'); p.add_argument('--hostname', required=True); p.add_argument('--email', required=True)
    for name in ('enroll', 'up', 'down', 'status', 'backup', 'check', 'render'):
        subs.add_parser(name)
    p = subs.add_parser('restore'); p.add_argument('archive', type=Path)
    args = parser.parse_args()
    root = args.state.resolve()
    private_directory(root)
    # Serialize lifecycle commands so enrollment and production never race on SQLite.
    with state_lock(root):
        if args.command == 'init':
            init(root, args.hostname, args.email)
            print('Initialized. Run enroll to create your account on localhost:8222.')
        elif args.command == 'render':
            render(root)
        elif args.command == 'enroll':
            if owners(root):
                raise ValueError('Enrollment is closed because an account already exists.')
            compose(root, False, 'down')
            compose(root, True, 'up', '-d', '--wait')
            print('Open http://localhost:8222 and create only the configured owner account. Then run up.')
        elif args.command == 'up':
            compose(root, True, 'down')
            check_owner(root)
            render(root)
            compose(root, False, 'up', '-d', '--wait')
        elif args.command == 'down':
            compose(root, True, 'down'); compose(root, False, 'down')
        elif args.command == 'status':
            compose(root, True, 'ps'); compose(root, False, 'ps')
        elif args.command == 'backup':
            stopped(root)
            print(backup(root))
        elif args.command == 'restore':
            stopped(root)
            restore(root, args.archive.resolve())
            print('Restored. Run up, then check.')
        elif args.command == 'check':
            check_owner(root); probe(root)


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, sqlite3.Error, tarfile.TarError) as error:
        print('Error:', error, file=sys.stderr)
        sys.exit(1)
