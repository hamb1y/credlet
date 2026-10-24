# Testing

## Credlet 0.2.0 debug pass

Verified on 2026-10-24:

- 31 Python regressions and 17 JavaScript tests, including legacy settings/app links, deployment identity, exact website rules and interrupted-session locking.
- Real Chrome 156.0.8078.47 and Firefox 158.0.1 extension UI with Argon2id, search, encrypted notes, edit/trash, copying, password/code filling, ambiguous-field rejection, passkey approval/cancellation and native fallback where supported.
- Independent official-client decryption and sync, real Caddy HTTPS/WSS notifications, full backup recovery, recovered passkey signing and deletion sync.
- Linux source UI and freshly frozen desktop UI against actual GTK username/password/code fields on the glibc 2.44 host. The frozen GUI runs with Python and Node removed from PATH.
- Offline packaged sign-in/vault/search/lock layout checks at 800×760 and 660×660. The release workflow runs these on Windows and Linux.
- Fresh server CLI packaging, state protection, paths containing spaces, byte-identical reviewer source rebuild, and zero Firefox linter errors/warnings.

The earlier platform-specific acceptance reports below explicitly identify their Lockbox 0.1.0 evidence. This pass did not repeat Android device or full Windows native-field acceptance. Windows receives build/runtime/offline GUI checks in CI; macOS remains deferred.

## Run the tests

Standard-library manager tests and extension tests:

```sh
python3 -m unittest discover -s tests -v
npm ci
npm test
npm run build
```

The integration test runs its own disposable server and TLS proxy. It also checks interoperability with the actual Credlet extension vault code. Add `--kdf argon2` to exercise Argon2id and `--geckodriver /path/to/geckodriver` to install the built extension and exercise its Firefox UI, including real WebAuthn requests. Use `--chromedriver /path/to/chromedriver --chrome /path/to/chrome` for Chrome for Testing instead. It creates a test account, signs in two isolated CLI profiles, checks encrypted sync and RFC 6238 TOTP, checks server files for the plaintext password, restores a full backup and verifies access with the existing client, then tests deletion sync. Browser-enabled runs also verify passkey signatures from a fresh client and after backup recovery. It never modifies real vault data or global CLI configuration.

On Linux x86_64 with Node.js, npm and OpenSSL:

```sh
python3 tools/fetch-test-runtime.py
npm install --prefix .tools @bitwarden/cli@2026.10.0 --no-audit --no-fund
python3 tests/integration.py \
  --vaultwarden .tools/vaultwarden --web-vault .tools/web-vault \
  --bw .tools/node_modules/.bin/bw --library-path .tools/lib
```

The fetcher verifies the pinned OCI index, platform manifest and layer digests. A system compatible with the binary's other dynamic dependencies is still required. Production uses the complete image. The default integration proxy is a test fixture. To test real Caddy HTTPS/WebSocket forwarding, run `python3 tools/fetch-caddy-test-runtime.py` and add `--caddy .tools/caddy` to the integration command. The complete generated Compose stack also passed HTTPS, encrypted clients, passkeys, WSS and full backup/recovery in an isolated Docker VM. See [container acceptance and repeatable setup](container-testing.md) for its scope and commands.


## Release automation and tested scope

The [Build and release workflow](../.github/workflows/release.yml) tests Python
state management on actual Linux and Windows runners, including interprocess
locking, backup recovery, policy gates and native-field guard regressions. It
builds and smoke-tests the real frozen desktop and server executables. Linux
also exercises real GTK fields in an isolated X display and accessibility bus.
The browser job runs cryptographic/passkey tests, Mozilla's extension linter,
and a byte-identical rebuild from the reviewer source ZIP.

These CI smoke checks do not replace complete GUI, Docker service or device
acceptance. Earlier disposable-environment acceptance and reproducible harnesses
are documented separately:

- [Complete Docker stack](container-testing.md)
- [Linux frozen UI and native fields](linux-testing.md)
- [Windows frozen UI and native fields](windows-testing.md)
- [Android native provider and Firefox Nightly](android-testing.md)

Windows CI checks the management CLI without running Linux Docker containers.
Full service acceptance used the isolated Linux Docker VM. macOS is deferred;
its source and regression tests remain, but no Mac binary is released.
