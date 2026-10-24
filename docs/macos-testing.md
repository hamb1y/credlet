# macOS build and native acceptance

macOS execution remains unverified. The source adapter, build and guarded Cocoa
fixture/harness are prepared for execution on an actual Mac. Linux unit tests
check executable identity and enabled/writable text-field decisions using
stubbed AX responses; they do not establish macOS Accessibility support.
Record actual results and artifact checksums in [the testing guide](testing.md).

## Build on the Mac

Use macOS **13.5 or newer**, a disposable graphical test user, Python with Tk, Node/npm and a local copy
of this project. Build on the intended architecture: arm64 on Apple Silicon or
x64 on Intel. The build packages the running architecture, not a universal app.

```sh
python3 -m venv .tools/macos-venv
. .tools/macos-venv/bin/activate
python -m pip install -r desktop/requirements-build.txt
npm ci --ignore-scripts --no-audit --no-fund
python desktop/build.py
```

PyObjC core, Cocoa, Quartz, CoreText and ApplicationServices are pinned to **12.2.2**;
[upstream Cocoa](https://pypi.org/project/pyobjc-framework-Cocoa/12.2.2/) and
[ApplicationServices](https://pypi.org/project/pyobjc-framework-ApplicationServices/12.2.2/)
publish Python 3.14 universal2 wheels. PyInstaller targets the interpreter's
current architecture and the build includes the checksum-verified Node runtime.
The macOS 13.5 baseline comes from the bundled Node 24 runtime's
[official platform requirements](https://github.com/nodejs/node/blob/v24.22.1/BUILDING.md#platform-list).

The output is `desktop/dist/Credlet.app` and a
`credlet-desktop-0.1.0-darwin-arm64.tar.gz` or
`credlet-desktop-0.1.0-darwin-x64.tar.gz` archive with adjacent SHA-256.
The README is staged as a bundle resource before signing. The build runs
`codesign --verify --deep --strict` before archiving; it does not append files to
the sealed app. PyInstaller's default is ad-hoc signing, described in its
[macOS signing notes](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing).
This is a development build, without Developer ID notarization.

## Runtime and actual GUI

Create the explicit private test marker, then check the frozen dependencies
with separately installed Python/Node absent from its PATH:

```sh
mkdir -p .tools/macos-test
chmod 700 .tools/macos-test
printf '%s\n' credlet-disposable-macos-test > .tools/macos-test/.disposable
env PATH=/usr/bin:/bin desktop/dist/Credlet.app/Contents/MacOS/Credlet \
  --check-runtime --report .tools/macos-test/runtime-report.json
cat .tools/macos-test/runtime-report.json
open desktop/dist/Credlet.app
```

A runtime diagnostic proves that the bundled dependencies load and the vault
starts locked. It does not prove app filling. For filling, macOS must grant
Accessibility access to Credlet through its normal System Settings prompt.
The test harness separately needs permission for its actual responsible
Terminal/Python process. Neither the application nor tests alter TCC databases
or approve their own permissions.

## Real Cocoa controls

Build the fixture with its own executable and bundle identity. A shared Python
interpreter is intentionally refused by the production adapter.

```sh
python -m PyInstaller --noconfirm --clean --onedir --windowed --noupx \
  --name CredletFixture --osx-bundle-identifier local.credlet.fixture \
  --distpath desktop/fixture-dist --workpath desktop/fixture-build \
  --specpath desktop/fixture-build tests/native_macos_fixture.py
python tests/native_macos.py \
  --fixture desktop/fixture-dist/CredletFixture.app \
  --disposable-root .tools/macos-test \
  --report .tools/macos-test/native-report.json
```

The harness refuses non-macOS hosts, a missing explicit marker, a test directory
with other-user access, an unexpected fixture bundle identity, an invalid
fixture signature or a report outside the marked directory. Its temporary
fixture controls are `NSTextField` and `NSSecureTextField`, not mocked AX objects.
The production adapter captures their real Accessibility references and fills
username/password/code values. Private IPC can focus/inspect the fixture or
change its availability; it cannot fill a vault value.

A successful report requires exact executable identity, correct real values,
password-role separation, rejection of hidden/disabled/read-only controls and
rejection after application exit. After the Mac test directory is validated,
a new run removes an old report before checking dependencies or permissions.
Private fixture
values and IPC files are removed on exit. A Cocoa run loop follows the
[upstream PyObjC application example](https://pyobjc.readthedocs.io/en/latest/examples/core/Scripts/HelloWorld/).

The adapter now re-reads the field's
[`kAXEnabledAttribute`](https://developer.apple.com/documentation/applicationservices/kaxenabledattribute)
before capture and filling, in addition to checking its writable value and text
role. The pinned ApplicationServices wheel exports this constant. Missing or
false enabled state is refused; four host decision tests cover this behavior.
Actual disabled/read-only behavior and hidden-field rejection still require
the Cocoa run. In particular, there is no independently verified Mac visibility
guard yet; a hidden-field acceptance failure must be fixed before claiming Mac
support.

## Attended source UI and encrypted-client acceptance

The native harness also has a `--desktop-ui` mode. It invokes the source app's
real Tk buttons and vault bridge, captures the packaged fixture through the
production AX adapter, verifies refusal before linking, fills actual native
username/password/code values and checks its saved settings, lock behavior and
Mac Quit callback's shutdown of the actual Node bridge.
The TOTP is checked independently. The normal native app-link confirmation is
attended: check the displayed fixture executable path and choose **Yes**.
The harness does not replace the dialog or grant Accessibility permission.

The full integration runner prepares a disposable HTTPS/Argon2id account and
passes its credentials and fixture CA through the child environment. Supply
Vaultwarden, Caddy and official CLI runtimes that actually execute on the Mac;
the Linux binaries cached by this workspace cannot be used on macOS. With those
runtimes, the marked directory and packaged Cocoa fixture prepared above:

```sh
python tests/integration.py \
  --vaultwarden /path/to/macos/vaultwarden \
  --web-vault /path/to/web-vault \
  --bw /path/to/bw \
  --caddy /path/to/macos/caddy --kdf argon2 \
  --desktop-macos .tools/macos-test \
  --macos-fixture desktop/fixture-dist/CredletFixture.app
```

The driver keeps the dialog instruction visible and allows three minutes for
the native checks and attended UI flow. If it times out, it stops its private
process group, including the owned fixture and vault bridge. Source settings
and inspected fixture values live only in the marked temporary test directory
and are removed by normal harness cleanup.

After the source UI succeeds, the official CLI must independently decrypt the
exact `credlet-app://macos/` URI for the fixture executable and verify the
original login password, TOTP, website URI and notes. The integration run also
checks authenticated WSS, full backup/recovery, the same app link through an
existing client after recovery and deletion sync. The guarded source harness
and integration entry point compile here, and both refuse this Linux host
before creating a fixture, launching a server or writing a report. Neither has
executed on macOS yet; no successful Mac source UI report exists. A successful
source run also writes `layout.json` containing public widget rectangles,
window/content offsets, interpreter versions and the fixture executable path.
It contains no entry contents, passwords, vault records or session keys. Its
SHA-256 is recorded in `source-ui-report.json`; the frozen driver requires that
matching successful report before using the geometry.

## Prepared packaged acceptance — Mac execution pending

After the native and source UI checks pass, run the same disposable integration
command with the additional argument:

```sh
  --macos-packaged-app desktop/dist/Credlet.app
```

This selects `tests/packaged_macos.py`, uses the existing successful source
geometry from `.tools/macos-test/layout.json` and writes a separate
`packaged-ui-report.json`. Use the source/build interpreter, same architecture,
fixture path and display settings when generating that geometry. Do not reuse
Windows or Linux layouts.

The driver verifies the bundle identity/signature and starts its frozen runtime
diagnostic with Python/Node absent from `PATH` and source-specific library
overrides removed. It then drives the real GUI through mouse/keyboard events
addressed to the owned PID, checking the running executable before input.
Core Graphics supplies window bounds. System-wide
[AX hit testing](https://developer.apple.com/documentation/applicationservices/1462077-axuielementcopyelementatposition)
must identify the owned PID at each click, and the owned app must be active
before each keyboard event. Events use
[`CGEventPostToPid`](https://developer.apple.com/documentation/coregraphics/cgevent/posttopid(_:)).
No clipboard, product test RPC or Tcl debugging endpoint is used.

Passing requires exposed GUI labels, actual HTTPS unlock, unchanged fixture
values after an unlinked fill, a real confirmation dialog exposing the exact
fixture executable, actual username/password/TOTP filling, private settings and
the sign-in form after locking. The app-link dialog is attended; wait for the
driver's **ACTION** instruction before choosing Yes. Finally, Command-Q must
exit the frozen GUI normally and stop its actual Node bridge child. Mac Quit
now routes through the app's shutdown handler using Tk's separate
[`::tk::mac::Quit` callback](https://www.tcl-lang.org/man/tcl8.6/TkCmd/tk_mac.htm).
The official CLI independently checks the encrypted link and preserved fields,
and the enclosing integration run requires recovery/WSS/deletion checks.

The driver compiles here; five Linux-host tests with stubbed OS responses check
its input refusal logic. These tests establish neither real event delivery nor
Tk's AX exposure on macOS. Missing labels, changed geometry or unsupported
input behavior fail the run and must be resolved on the Mac; no timed-click
fallback turns them into a pass. No Mac build or successful source/frozen report
exists yet. SSH access alone
does not establish a logged-in GUI session or Accessibility permission; an
actual interactive Mac or appropriately configured macOS runner is required.
