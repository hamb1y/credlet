"""Run frozen GUI acceptance inside the owned LTS container; input is private SSH stdin."""
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit


def main():
    if os.getuid() != 1000 or not Path('/.dockerenv').exists():
        raise RuntimeError('This runner requires the disposable build container user.')
    payload = json.load(sys.stdin)
    environment = payload['environment']
    server = urlsplit(environment['TEST_SERVER'])
    if server.scheme != 'https' or server.hostname != 'localhost' or not server.port or server.port < 1024:
        raise RuntimeError('Only the disposable localhost HTTPS fixture is supported.')

    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            # QEMU user networking routes this address to the host loopback.
            # Relay bytes only: Node still verifies the original localhost TLS certificate.
            with socket.create_connection(('10.0.2.2', server.port), timeout=10) as upstream:
                peers = (self.request, upstream)
                while True:
                    ready, _, _ = select.select(peers, [], [], 30)
                    if not ready:
                        return
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.request else self.request).sendall(data)

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    executable = Path('/work/desktop/dist/Lockbox/Lockbox')
    with tempfile.TemporaryDirectory(prefix='lockbox-lts-') as temporary:
        root = Path(temporary)
        ca = root / 'ca.pem'
        ca.write_text(payload['certificate'])
        env = {**os.environ, **environment, 'NODE_EXTRA_CA_CERTS': str(ca),
            'PYTHONDONTWRITEBYTECODE': '1'}
        with Server(('127.0.0.1', server.port), Relay) as relay:
            thread = threading.Thread(target=relay.serve_forever, daemon=True)
            thread.start()
            try:
                subprocess.run([sys.executable, '/work/tests/native_linux.py',
                    '--packaged-app', str(executable)], env=env, check=True, timeout=100)
            finally:
                relay.shutdown()
                thread.join(timeout=5)
    report = {'ok': True, 'libc': platform.libc_ver(), 'python': sys.version,
        'executableSha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'bridgeSha256': hashlib.sha256((executable.parent / '_internal/runtime/bridge.mjs').read_bytes()).hexdigest(),
        'passed': ['frozen runtime', 'HTTPS unlock', 'explicit encrypted app link',
            'native username/password/TOTP fill', 'private settings and lock',
            'password role, hidden/disabled/read-only-field and closed-app guards']}
    print('LOCKBOX_LINUX_REPORT ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
