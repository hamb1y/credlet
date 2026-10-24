"""Cross-process locking and real host state permissions, including Windows ACLs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import credlet


class StateBoundaryTests(unittest.TestCase):
    def test_two_processes_cannot_enter_the_same_state_lock(self):
        script = '''import sys
from pathlib import Path
import credlet
print('waiting', flush=True)
with credlet.state_lock(Path(sys.argv[1])):
    print('acquired', flush=True)
    sys.stdin.readline()
'''
        with tempfile.TemporaryDirectory() as temporary:
            processes = []
            try:
                first = subprocess.Popen([sys.executable, '-u', '-c', script, temporary],
                    cwd=credlet.ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                processes.append(first)
                self.assertEqual(first.stdout.readline().strip(), 'waiting')
                self.assertEqual(first.stdout.readline().strip(), 'acquired')
                # The second child's acquired marker is written to a file so the
                # parent can check its absence without blocking on a pipe read.
                marker = Path(temporary) / 'acquired'
                second_script = script.replace("print('acquired', flush=True)",
                    "Path(sys.argv[2]).write_text('acquired')")
                second = subprocess.Popen([sys.executable, '-u', '-c', second_script,
                    temporary, str(marker)], cwd=credlet.ROOT, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, text=True)
                processes.append(second)
                self.assertEqual(second.stdout.readline().strip(), 'waiting')
                time.sleep(0.3)
                self.assertFalse(marker.exists())
                self.assertIsNone(second.poll())
                first.communicate('\n', timeout=10)
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(marker.exists())
                second.communicate('\n', timeout=10)
                self.assertEqual(first.returncode, 0)
                self.assertEqual(second.returncode, 0)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()

    def test_state_permissions_are_private_on_the_actual_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state with spaces ' and brackets [x]"
            credlet.init(root, 'vault.example.com', 'owner@example.com')
            if os.name != 'nt':
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)
                self.assertEqual((root / 'config.json').stat().st_mode & 0o777, 0o600)
                return
            script = '''$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:CREDLET_ACL_TEST
@{protected=$acl.AreAccessRulesProtected; owner=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; rules=@($acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) | ForEach-Object {$_.IdentityReference.Value})} | ConvertTo-Json -Compress
'''
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                '-Command', script], check=True, capture_output=True, text=True,
                env={**os.environ, 'CREDLET_ACL_TEST': str(root)})
            acl = json.loads(result.stdout)
            self.assertTrue(acl['protected'])
            self.assertEqual(set(acl['rules']), {acl['owner'], 'S-1-5-18'})
