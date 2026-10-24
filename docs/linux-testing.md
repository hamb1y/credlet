# Linux LTS desktop build and acceptance

The detailed acceptance evidence below was recorded for **Lockbox 0.1.0**, before the Credlet rename. Commands use the current Credlet names; historical archive sizes and hashes refer to the original Lockbox artifacts. See [current testing](testing.md) for checks on the renamed version.

The Linux x64 build recipe uses Ubuntu **22.04**, glibc **2.35**, distribution
Python **3.10** with Tk/PyGObject, PyInstaller **6.22.3** and the checksum-verified
Node **24.22.1** runtime. Its official Ubuntu amd64 base is pinned in
`desktop/linux/Dockerfile` to
`sha256:98510ac07bb4545e389be502a8918b385c018bfe4ceeb5ac7e0375c782268b04`.
The package inventory and archive SHA-256 are recorded beside each built archive
in its `.build.json` file. Apt packages receive the baseline's current updates;
the inventory records the versions actually used.

Verified on **2026-10-24**: the same archive passed the complete frozen GUI,
HTTPS/Argon2id, real GTK username/password/TOTP filling, official-client sync,
WSS, recovery and deletion checks inside Ubuntu **22.04.5 / glibc 2.35** and on
the newer **glibc 2.44** host. Both integration processes exited **0**. All **75**
bundled ELF files were inspected; the highest required glibc symbol version is
**2.35**. Real native checks also reject hidden, disabled, read-only, closed and
mismatched-role fields without changing their contents.

The earlier `desktop/dist/lockbox-desktop-0.1.0-linux-x64.tar.gz` is
**61,137,592 bytes**, SHA-256
`302f846ff89aa7e83d99bbb41fa3d74280d45fda948e7cf1975f75fa68784838`.
`.tools/linux-lts/release-evidence.json` records the two full runs and executable
digests. The previous glibc 2.44 build remains in
`.tools/linux-lts/previous-linux-build`.

Build on Linux x64 with Docker. The root `.dockerignore` permits only the image's
dependency list and Dockerfile into its build context. Run the build against a
separate source copy so its dependencies and output do not replace another
platform's work:

```sh
docker build -f desktop/linux/Dockerfile -t credlet-desktop-lts:22.04 .
mkdir -p .tools/linux-build-source
tar --exclude='desktop/build' --exclude='desktop/dist' \
  --exclude='desktop/fixture-build' --exclude='desktop/fixture-dist' \
  --exclude='*/__pycache__' -cf - \
  package.json package-lock.json desktop extension/src tests \
  | tar -xf - -C .tools/linux-build-source
docker run --rm --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" -e HOME=/tmp/credlet-build-home \
  -v "$PWD/.tools/linux-build-source:/work" credlet-desktop-lts:22.04
```

The result is under `.tools/linux-build-source/desktop/dist/`: the complete
`Credlet` directory, tar archive, checksum and build inventory. Keep the entire
application directory together. The frozen executable's `--check-runtime`
diagnostic checks its bundled dependencies without unlocking a vault. Runtime
diagnostics alone do not establish working native application filling.

The archive needs a glibc desktop and a working X11/XWayland/Tk and AT-SPI
accessibility session. A glibc baseline does not establish compatibility with
every distribution, Wayland compositor or application's accessibility tree.
Musl/Alpine desktops are outside this archive's target.

## Real GUI and HTTPS checks

`tests/native_linux.py` creates a private authenticated Xvfb display, session bus,
accessibility bus and a separate compiled GTK application. It checks actual
username/password/code fields, executable identity, password-role separation and
hidden/disabled/read-only/closed-field rejection. `tests/packaged_ui.py` drives the real frozen Tk
interface over that private display, removing Python/Node from its `PATH` and
source-specific library overrides.

The `--desktop-linux-container` integration option runs that frozen interface
inside the owned Ubuntu build container. It is intentionally fixed to the
disposable VM described in [container testing](container-testing.md), its pinned
SSH identity, QEMU vendor and disk marker. Its source/build path is
`/srv/credlet-test/desktop-lts`, and its local image is
`credlet-desktop-lts:22.04`. This test option does not select the host Docker
daemon or an arbitrary remote machine.

The older AT-SPI release exposed a compatibility bug: it lacks
`clear_cache_single`. The adapter now uses the supported
[`clear_cache` method](https://docs.gtk.org/atspi2/method.Accessible.clear_cache.html)
before checking the captured field's current visibility and editability. Both
baseline and newer-host native field guards pass with this change.

```sh
python3 tests/integration.py \
  --vaultwarden .tools/vaultwarden --web-vault .tools/web-vault \
  --library-path .tools/lib --bw .tools/node_modules/.bin/bw \
  --caddy .tools/caddy --kdf argon2 --desktop-linux-container
```

The host supplies a fresh disposable HTTPS vault. Fixture credentials travel in
encrypted SSH stdin and remain in the test processes' memory/environment. The
container has a read-only filesystem/source mount and a temporary writable
`/tmp`, with capabilities dropped. A container-only loopback TCP relay reaches
the host through QEMU networking; it does not terminate TLS. The client still
verifies the fixture CA and the `localhost` certificate. No host trust-store or
firewall change is required.

The full run checks HTTPS/Argon2id unlock, refusal before linking, explicit
encrypted app linking, actual native username/password/TOTP fill, only the three
allowed saved settings, lock and normal shutdown. Independent official CLI
decryption checks the app URI and preservation of the original password, TOTP,
URL and notes. The same integration run checks authenticated WSS delivery,
backup/restore into a fresh directory, existing-client access and deletion sync.
`.tools/linux-lts/full-ui-report.json` records container GUI success and executable
digests; the full integration process must also exit successfully for the
subsequent sync/recovery checks to count.

The transferred archive also passed the host command documented under
[desktop acceptance](../desktop/README.md). This checks the same frozen build
against the newer desktop libraries separately from the LTS container.

Primary references: [official Ubuntu image](https://hub.docker.com/_/ubuntu),
[PyInstaller's GNU/Linux compatibility guidance](https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible).
