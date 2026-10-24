# Credlet desktop companion

The desktop companion connects to the same self-hosted vault and fills a captured native application field through accessibility APIs. It runs as a local desktop application, with a private Node subprocess for vault encryption and HTTPS. It does not open a local HTTP server or copy secrets to the clipboard.

Earlier Lockbox 0.1.0 Linux and Windows bundles passed HTTPS unlock, explicit app linking and real native username/password/TOTP filling through their actual frozen interfaces. Credlet 0.2.0 adds an offline packaged GUI check on both build runners; see [testing](../docs/testing.md) for the current full acceptance scope. The macOS Accessibility adapter is implemented but still needs a build and execution on macOS. Browser passkeys use the browser extension; this companion fills native username/password/TOTP fields.

## Standalone Linux bundle

Extract `desktop/dist/credlet-desktop-0.2.0-linux-x64.tar.gz` and run `Credlet/Credlet`. Keep the entire extracted directory together. It contains Python/Tk, accessibility bindings, Node and the encrypted vault bridge, so a separate Python or Node installation is unnecessary. A working desktop accessibility bus is still required for filling.

The Linux x64 LTS build uses Ubuntu 22.04 with glibc 2.35. See [Linux build and acceptance](../docs/linux-testing.md) for the recipe and tested scope. A working desktop accessibility session is required; the glibc baseline alone does not establish every distribution or application's compatibility. The archive has adjacent `.sha256` and `.build.json` files. Run `Credlet/Credlet --check-runtime` to check its bundled dependencies without connecting to a vault. `--report path.json` can save that diagnostic result.

## Build on the target operating system

Use Python with Tk and the platform accessibility dependencies described below. Install `desktop/requirements-build.txt` into an isolated Python environment. Linux builders need access to distribution-provided PyGObject, for example through a virtual environment created with `--system-site-packages`.

```sh
npm ci
python3 -m pip install -r desktop/requirements-build.txt
python3 desktop/build.py
```

The build downloads Node LTS **24.22.1**, verifies the archive against the upstream HTTPS checksum manifest, records the archive digest and includes Node's license. It bundles the vault bridge with esbuild and creates a PyInstaller application plus archive/checksum in `desktop/dist/`. Node archives are cached in `desktop/build/`. `--node-only` fetches and verifies just that runtime.

Build on Windows for a Windows executable/ZIP, and on macOS for a `.app`/tar archive. The earlier Lockbox Windows x64 ZIP passed actual frozen UI acceptance; macOS output remains unverified. Distribution signing and installer integration are outstanding. [PyInstaller's packaging model](https://pyinstaller.org/en/stable/operating-mode.html) requires a build on each target operating system.

## Standalone Windows bundle

Extract `desktop/dist/credlet-desktop-0.2.0-win-x64.zip` and run `Credlet\Credlet.exe`. Keep the complete extracted directory together. Python, Tk, comtypes, Node and the vault bridge are bundled; separate Python or Node installations are unnecessary. Check the adjacent `.sha256` file after transferring the ZIP. `Credlet\Credlet.exe --check-runtime --report runtime-report.json` checks dependencies without unlocking a vault.

The earlier Lockbox 0.1.0 development bundle passed on Windows 11 Enterprise LTSC x64, build 26100.1742, using real Win32 controls. Its actual UI passed HTTPS/Argon2id unlock, explicit native confirmation and encrypted app linking, username/password/TOTP filling, private settings and lock, with Python and Node absent from `PATH`. Independent official-client decryption, WSS, backup recovery and deletion sync passed. Hidden, disabled, read-only, closed and mismatched-role fields are rejected. See [Windows build and acceptance](../docs/windows-testing.md). Broader Windows versions/applications and signed distribution remain unverified.

## Run from source

Install Python with Tk, Node.js 22 or newer, and the platform accessibility dependencies. From the project directory:

```sh
npm ci
python3 -m desktop.app
```

On Linux, install PyGObject and AT-SPI 2 using your distribution packages, and enable application accessibility in your desktop session. Typical package names are `python-gobject`, `at-spi2-core` and `tk` on Arch, or `python3-gi`, `gir1.2-atspi-2.0` and `python3-tk` on Debian/Ubuntu. The target application must expose editable accessibility fields.

Windows source execution requires `comtypes` in the Python environment. macOS requires `pyobjc-framework-ApplicationServices` and `pyobjc-framework-Cocoa`; the first capture prompts for Accessibility permission. The macOS path still needs platform acceptance.

The macOS development bundle targets macOS 13.5 or newer because of its pinned Node runtime. See [Mac build and native checks](../docs/macos-testing.md). The build stages documentation before sealing the `.app` and checks its signature before archiving. Mac app links use the resolved executable path; a declared bundle identifier alone cannot authorize another binary.

Enter the HTTPS server URL, owner email and master password. If vault login uses authenticator two-step login, enter its current code as well. Only the server address, email and device identifier are saved. Vault keys, session tokens and decrypted items stay in memory; the vault locks after five minutes or when the process closes.

## Fill an application

1. Choose **Capture app field…**, then focus the desired field in the target application within three seconds.
2. Review the captured executable path or application identity. Select a login and choose **Link login to app**, then confirm. This adds an encrypted `credlet-app://…` URI to that login and preserves its other vault fields.
3. Choose username, password or code and select **Fill selected field**. Review the result and submit in the target application yourself. Capture again when moving to a different field.

Passwords require a password accessibility role. Username and code filling require a non-password field. The companion rechecks the captured application identity and field before writing. It keeps the specific accessibility reference, so focusing a different window does not redirect the secret. Browsers and generic shared interpreter executables are refused; use the browser extension for website origin matching.

The companion lists and links existing logins. Create, edit and delete logins in the extension or web vault. Protected items require a fresh master-password verification before linking or filling. Applications that do not expose a writable accessibility field are unsupported by this filling method.

## Linux acceptance

```sh
python3 tests/native_linux.py
python3 tests/integration.py \
  --vaultwarden .tools/vaultwarden --web-vault .tools/web-vault \
  --library-path .tools/lib --bw .tools/node_modules/.bin/bw \
  --caddy .tools/caddy --desktop-linux
```

The native fixture uses a private Xvfb display, session bus and accessibility bus. It tests actual GTK fields, password-role checks, and rejection after a field is hidden or its application closes. The integration option additionally drives the actual Tk interface and Node subprocess against a disposable HTTPS vault: unlock, reject an unlinked login, explicitly link, fill username/password/TOTP, inspect saved settings and lock. Development runtime prerequisites are described in the project README; these tests do not establish Windows/macOS compatibility.

Add `--desktop-runtime desktop/dist/Credlet/_internal/runtime` to exercise the bundled Node runtime and bridge through the same UI acceptance. This passed, including independent official-client decryption of the app link and preservation of the original login fields, WSS delivery and full backup recovery. The packaged executable separately passed its runtime diagnostic and an actual GUI launch with Python and Node absent from `PATH`.

Use `--packaged-app desktop/dist/Credlet/Credlet` instead to drive the frozen application's actual controls over the fixture's authenticated private X display. This passed HTTPS unlock, explicit app linking, real native username/password/TOTP filling, private settings, lock and normal shutdown with Python/Node absent from `PATH`. This checks the bundled Python/accessibility libraries as well as the vault bridge.
