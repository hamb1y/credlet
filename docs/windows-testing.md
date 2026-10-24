# Windows build and native acceptance

Windows x64 builds, the standalone runtime diagnostic, actual Win32 field tests,
full source UI integration and the packaged application's actual GUI acceptance
have passed. Runtime versions and limits are recorded in [the testing guide](testing.md).

## Build on Windows

Use a Windows x64 machine with Python including Tcl/Tk, Node/npm and a local copy
of this project. Install build dependencies and build on that operating system:

```powershell
python -m pip install -r desktop/requirements-build.txt
npm ci --ignore-scripts --no-audit --no-fund
python desktop/build.py
```

The build downloads its pinned Node runtime and checks the official SHA-256
manifest. PyInstaller packages Python/Tk, the Windows accessibility dependencies
and the bundled Node vault bridge. Its output is
`desktop/dist/lockbox-desktop-0.1.0-win-x64.zip` and an adjacent `.sha256` file.
Distribution signing and installer integration are separate work.

Check the frozen runtime without signing into a vault:

```powershell
desktop\dist\Lockbox\Lockbox.exe --check-runtime --report runtime-report.json
Get-Content runtime-report.json
```

## Actual native fields

The acceptance harness deliberately requires the disposable VM computer name
`LOCKBOX-TEST`. Run it in that VM's interactive desktop as `lockboxtest`. A WinRM
process by itself runs outside the interactive desktop and cannot establish
native application filling.

```powershell
python -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name LockboxFixture --distpath desktop/fixture-dist --workpath desktop/fixture-build --specpath desktop/fixture-build tests/native_windows_fixture.py
python tests/native_windows.py --fixture desktop/fixture-dist/LockboxFixture/LockboxFixture.exe --report native-report.json
```

The fixture creates real Win32 `EDIT` controls, including an `ES_PASSWORD` field,
in its own packaged executable. The harness captures them through the production
UI Automation adapter and verifies their actual values. It also checks field
roles and refusal after hiding, disabling, making a field read-only or closing
the application. Fixture commands only control/inspect these owned test fields;
all vault filling goes through the production adapter.

## Full encrypted-client integration from the Linux host

The remote harness expects only the owned local VM endpoint
`http://127.0.0.1:15985/wsman`, computer `LOCKBOX-TEST`, user `lockboxtest` and
the marker `C:\LockboxTest\.disposable` containing
`lockbox-disposable-windows-vm`. Source, Python and the compiled fixture must be
under `C:\LockboxTest`; the bridge runtime comes from the Windows build above.

Create a private `0600` host JSON file with `disposable: true`, that `wsman`
endpoint, `username: "lockboxtest"` and the disposable VM's random password. Do
not put its contents in source control. Install `pywinrm==0.5.0` in a test-only
host virtual environment and run:

```sh
.tools/windows-venv/bin/python tests/integration.py \
  --vaultwarden .tools/vaultwarden --web-vault .tools/web-vault \
  --library-path .tools/lib --bw .tools/node_modules/.bin/bw \
  --caddy .tools/caddy --kdf argon2 \
  --desktop-windows .tools/windows-test/session.json
```

The harness runs the real Tk UI as an interactive scheduled task. It unlocks
the disposable HTTPS vault, refuses an unlinked login, confirms an explicit app
link, fills real native username/password/TOTP fields, checks settings and locks.
The official CLI independently decrypts the resulting app link and verifies the
preserved login fields. The surrounding integration run checks encrypted sync,
authenticated WSS, backup recovery and deletion sync.

The source UI run also records public widget rectangles in the guest's
`C:\LockboxTest\acceptance\layout.json`. After that run passes, append
`--windows-packaged` to the host command to drive the actual built executable
through mouse/keyboard events on that same Windows/Tk/DPI runtime. Input is
restricted to windows owned by that exact application process. The driver
confirms the actual native app-link dialog and inspects real fixture field
values; it opens no application debugging endpoint. Python and Node are removed
from the executable's `PATH`, and its bundled-runtime diagnostic must pass.

Keep the VM logged into its disposable interactive desktop and awake before
starting. During acceptance the test thread requests an active display and
restores its normal execution state afterward; it does not change power-policy
settings.

A temporary guest loopback port proxy reaches the host's fixture through QEMU's
`10.0.2.2` address while keeping the original `localhost` certificate name. TLS
verification remains enabled; only the Node fixture process receives the test
CA. Cleanup removes the proxy, scheduled task, private fixture credentials and
temporary CA file. Windows testing never changes the host trust store.

## VM setup notes

Use Microsoft's [official Windows 11 Enterprise evaluation image](https://www.microsoft.com/en-us/evalcenter/download-windows-11-enterprise)
with a new disposable virtual disk, UEFI and TPM 2.0. Expose no host physical
disks. This workspace uses an isolated KVM guest and a loopback-only WinRM
forward; test-only remoting settings belong exclusively to that VM.

An unattended `RunSynchronousCommand/Path` accepts at most 259 characters, per
[Microsoft's setting reference](https://learn.microsoft.com/en-us/windows-hardware/customize/desktop/unattend/microsoft-windows-deployment-runsynchronous-runsynchronouscommand-path).
Split setup commands or invoke a staged script. The initial VM setup failed
validation because its inline remoting command exceeded this limit; that is a
test environment failure and provides no application acceptance evidence.
