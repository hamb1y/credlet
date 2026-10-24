"""Run native acceptance in the owned Windows VM's interactive user session.

Host dependency: pywinrm. The endpoint, guest and paths are deliberately fixed to
the disposable local VM; this never selects a personal Windows installation.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class Remote:
    def __init__(self, configuration):
        import winrm
        path = Path(configuration).resolve()
        if path.stat().st_mode & 0o077:
            raise RuntimeError('Windows fixture credentials must be private (0600).')
        config = json.loads(path.read_text())
        if config.get('disposable') is not True or config.get('wsman') != 'http://127.0.0.1:15985/wsman':
            raise RuntimeError('Refusing a Windows endpoint other than the owned local test VM.')
        if config.get('username') != 'lockboxtest': raise RuntimeError('Wrong Windows fixture user.')
        self.session = winrm.Session(config['wsman'],
            auth=(config['username'], config['password']),
            transport='ntlm', message_encryption='always', operation_timeout_sec=20, read_timeout_sec=30)
        self.ps("if ($env:COMPUTERNAME -ne 'LOCKBOX-TEST' -or (Get-Content 'C:\\LockboxTest\\.disposable').Trim() -ne 'lockbox-disposable-windows-vm') { throw 'Wrong VM' }")

    def ps(self, script):
        result = self.session.run_ps("$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; " + script)
        if result.status_code:
            # Do not echo an entire failed script: upload scripts can contain test credentials.
            raise RuntimeError('Windows fixture command failed, exit ' + str(result.status_code))
        return result.std_out.decode('utf-8-sig').strip()

    def put(self, destination, contents):
        if len(contents) > 1024 * 1024: raise RuntimeError('Fixture uploads must be small files.')
        path = quote(destination)
        expected = hashlib.sha256(contents).hexdigest()
        previous = self.ps('if(Test-Path ' + path + '){(Get-FileHash -Algorithm SHA256 ' + path + ').Hash}').lower()
        if previous == expected: return
        # Stream bytes through encrypted WinRS stdin. Embedding file data in
        # -EncodedCommand can exceed Windows' process command-line limit.
        code = "$ErrorActionPreference='Stop'; $f=[IO.File]::Create(" + path + "); try {[Console]::OpenStandardInput().CopyTo($f)} finally {$f.Dispose()}"
        encoded = base64.b64encode(code.encode('utf-16le')).decode('ascii')
        protocol = self.session.protocol
        shell = protocol.open_shell(); command = None
        try:
            command = protocol.run_command(shell, 'powershell.exe', ['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded])
            for offset in range(0, len(contents), 32768):
                protocol.send_command_input(shell, command, contents[offset:offset + 32768])
            protocol.send_command_input(shell, command, b'', end=True)
            _out, _error, status = protocol.get_command_output(shell, command)
            if status: raise RuntimeError('Windows fixture stream upload failed.')
        finally:
            if command: protocol.cleanup_command(shell, command)
            protocol.close_shell(shell)
        actual = self.ps('(Get-FileHash -Algorithm SHA256 ' + path + ').Hash').lower()
        if actual != expected: raise RuntimeError('Windows fixture upload checksum mismatch.')


def exercise(configuration, environment, certificate, packaged=False):
    remote = Remote(configuration)
    server = urlsplit(environment['TEST_SERVER'])
    if server.scheme != 'https' or server.hostname != 'localhost' or not server.port or server.port < 1024:
        raise RuntimeError('Windows acceptance requires the disposable localhost HTTPS fixture.')
    root = r'C:\LockboxTest\acceptance'
    remote.ps('New-Item -ItemType Directory -Force -Path ' + quote(root) + ' | Out-Null')
    remote.ps('& icacls ' + quote(root) + " /inheritance:r /grant:r 'LOCKBOX-TEST\\lockboxtest:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null; " +
        'if($LASTEXITCODE -ne 0){throw "Private fixture directory ACL failed"}')
    remote.put(root + r'\ca.pem', Path(certificate).read_bytes())
    remote.put(r'C:\LockboxTest\source\tests\native_windows.py', Path(__file__).with_name('native_windows.py').read_bytes())
    if packaged:
        remote.put(r'C:\LockboxTest\source\tests\packaged_windows.py', Path(__file__).with_name('packaged_windows.py').read_bytes())
    variables = {name: environment[name] for name in ('TEST_SERVER', 'TEST_EMAIL', 'TEST_PASSWORD', 'TEST_ITEM_PASSWORD')}
    variables['NODE_EXTRA_CA_CERTS'] = root + r'\ca.pem'
    remote.put(root + r'\environment.json', json.dumps(variables).encode())
    ui = (r'--packaged-app C:\LockboxTest\source\desktop\dist\Lockbox\Lockbox.exe --layout C:\LockboxTest\acceptance\layout.json'
        if packaged else r'--desktop-ui --runtime-directory C:\LockboxTest\source\desktop\build\runtime')
    command = (r'@echo off' + '\r\n' + r'cd /d C:\LockboxTest\source' + '\r\n' +
        r'C:\LockboxTest\python\python.exe -u tests\native_windows.py --fixture C:\LockboxTest\source\desktop\fixture-dist\LockboxFixture\LockboxFixture.exe --report C:\LockboxTest\acceptance\report.json ' + ui +
        r' --environment C:\LockboxTest\acceptance\environment.json > C:\LockboxTest\acceptance\run.log 2>&1' + '\r\n')
    remote.put(root + r'\run.cmd', command.encode())
    port = str(server.port)
    task = 'LockboxNativeAcceptance'
    try:
        remote.ps('Start-Service iphlpsvc; & netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=' + port + ' connectaddress=10.0.2.2 connectport=' + port + '; if ($LASTEXITCODE -ne 0) {throw "Port forwarding failed"}')
        remote.ps('Remove-Item ' + quote(root + r'\report.json') + ' -ErrorAction SilentlyContinue; ' +
            "$action=New-ScheduledTaskAction -Execute 'C:\\Windows\\System32\\cmd.exe' -Argument '/d /c C:\\LockboxTest\\acceptance\\run.cmd'; " +
            "$principal=New-ScheduledTaskPrincipal -UserId 'LOCKBOX-TEST\\lockboxtest' -LogonType Interactive -RunLevel Limited; " +
            '$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 4); ' +
            'Register-ScheduledTask -TaskName ' + quote(task) + ' -Action $action -Principal $principal -Settings $settings -Force | Out-Null; ' +
            'Start-ScheduledTask -TaskName ' + quote(task))
        deadline = time.monotonic() + 200
        while time.monotonic() < deadline:
            output = remote.ps('if(Test-Path ' + quote(root + r'\report.json') + '){Get-Content -Raw ' + quote(root + r'\report.json') + '}')
            if output:
                result = json.loads(output); assert result['ok']
                for entry in result['passed']: print('PASS Windows ' + entry, flush=True)
                return result
            status = remote.ps('(Get-ScheduledTask -TaskName ' + quote(task) + ').State')
            if status != 'Running':
                log = remote.ps('if(Test-Path ' + quote(root + r'\run.log') + '){Get-Content -Raw ' + quote(root + r'\run.log') + '}')
                raise RuntimeError('Windows native acceptance stopped: ' + log)
            time.sleep(1)
        raise RuntimeError('Windows interactive native acceptance timed out.')
    finally:
        remote.ps('Stop-ScheduledTask -TaskName ' + quote(task) + ' -ErrorAction SilentlyContinue; ' +
            'Unregister-ScheduledTask -TaskName ' + quote(task) + ' -Confirm:$false -ErrorAction SilentlyContinue; ' +
            '& netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=' + port + ' | Out-Null; ' +
            'Remove-Item ' + quote(root + r'\environment.json') + ',' + quote(root + r'\ca.pem') + ' -ErrorAction SilentlyContinue')
