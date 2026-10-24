"""Frozen Linux acceptance through the pinned SSH identity of the owned QEMU VM."""
import json
from pathlib import Path
import secrets
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = '/srv/lockbox-test/desktop-lts'
IMAGE = 'lockbox-desktop-lts:22.04'


def ssh(command, **kwargs):
    guard = ('set -eu; '
        'test "$(cat /srv/lockbox-test/.disposable)" = lockbox-disposable-linux-vm; '
        'test "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU; ')
    return subprocess.run(['ssh', '-p', '22993', '-i', str(ROOT / '.tools/linux-vm/id_ed25519'),
        '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile=' + str(ROOT / '.tools/linux-vm/known_hosts'),
        '-o', 'ConnectTimeout=10', 'root@127.0.0.1', guard + command],
        capture_output=True, text=True, **kwargs)


def exercise(environment, certificate):
    for name in ('linux_container_guest.py', 'native_linux.py', 'native_fixture.c', 'packaged_ui.py'):
        # These public test scripts contain no fixture credentials.
        uploaded = ssh('cat > ' + shlex.quote(SOURCE + '/tests/' + name),
            input=Path(__file__).with_name(name).read_text(), timeout=20)
        if uploaded.returncode:
            raise RuntimeError('Could not update the owned Linux test harness: ' + uploaded.stderr)
    inspected = ssh('docker image inspect --format ' + shlex.quote('{{.Id}}') + ' ' + IMAGE, timeout=20)
    if inspected.returncode:
        raise RuntimeError('The disposable LTS build image is unavailable: ' + inspected.stderr)
    destination = ROOT / '.tools/linux-lts/full-ui-report.json'
    destination.unlink(missing_ok=True)
    name = 'lockbox-lts-acceptance-' + secrets.token_hex(6)
    command = ['docker', 'run', '--rm', '--name', name, '--label', 'local.lockbox.test=lts-acceptance',
        '-i', '--network', 'host', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--read-only', '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=512m',
        '--tmpfs', '/tmp/.X11-unix:rw,nosuid,nodev,mode=1777',
        '-v', SOURCE + ':/work:ro', inspected.stdout.strip(),
        'python', '-u', 'tests/linux_container_guest.py']
    payload = {'environment': {key: environment[key] for key in
        ('TEST_SERVER', 'TEST_EMAIL', 'TEST_PASSWORD', 'TEST_ITEM_PASSWORD')},
        'certificate': Path(certificate).read_text()}
    try:
        result = ssh(shlex.join(command), input=json.dumps(payload), timeout=130)
        if result.returncode:
            raise RuntimeError('LTS frozen GUI acceptance failed: ' + result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        report = json.loads(next(line.removeprefix('LOCKBOX_LINUX_REPORT ')
            for line in lines if line.startswith('LOCKBOX_LINUX_REPORT ')))
        if not report.get('ok'):
            raise RuntimeError('LTS frozen GUI acceptance did not pass.')
        report['imageId'] = inspected.stdout.strip()
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + '\n')
        for line in lines:
            if not line.startswith('LOCKBOX_LINUX_REPORT '):
                print(line, flush=True)
        return report
    finally:
        # The random container name is scoped to this invocation; no other workload is selected.
        ssh('docker rm -f ' + shlex.quote(name) + ' >/dev/null 2>&1 || true', timeout=20)
