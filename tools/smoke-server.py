#!/usr/bin/env python3
"""Exercise the actual frozen CLI with isolated state, without a Docker daemon."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    source = Path(sys.argv[1]).resolve()
    executable_name = 'credlet-server.exe' if sys.platform == 'win32' else 'credlet-server'
    with tempfile.TemporaryDirectory(prefix='credlet release smoke ') as temporary:
        bundle = Path(temporary) / 'server bundle'
        shutil.copytree(source, bundle)
        executable = bundle / executable_name
        subprocess.run([str(executable), '--help'], check=True)
        # No --state: verify PyInstaller uses the executable's folder rather than
        # its internal library extraction directory or the working directory.
        command = [str(executable), 'init', '--hostname', 'vault.example.com',
                   '--email', 'owner@example.com']
        subprocess.run(command, cwd=temporary, check=True)
        state = bundle / 'state'
        config = json.loads((state / 'compose.json').read_text())
        vault = config['services']['vault']
        assert vault['environment']['SIGNUPS_ALLOWED'] == 'false'
        # Windows runner temp paths may use a short-name alias; the frozen CLI
        # resolves it to its canonical spelling before writing Compose files.
        assert Path(vault['volumes'][0]['source']).samefile(state / 'data')
        assert 'ports' not in vault
        assert not (bundle / '_internal/state').exists()
        before = (state / 'config.json').read_bytes()
        result = subprocess.run(command, cwd=temporary, capture_output=True, text=True)
        assert result.returncode == 1 and 'Already initialized' in result.stderr
        assert (state / 'config.json').read_bytes() == before
        subprocess.run([str(executable), 'render'], cwd=temporary, check=True)
    print('PASS frozen server CLI, paths with spaces, policy and existing-state protection')


if __name__ == '__main__':
    main()
