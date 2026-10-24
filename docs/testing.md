# Testing

Standard-library manager tests and extension tests:

```sh
python3 -m unittest discover -s tests -v
npm ci
npm test
npm run build
```

The integration test runs its own disposable server and TLS proxy. It also checks interoperability with the actual Lockbox extension vault code. Add `--kdf argon2` to exercise Argon2id and `--geckodriver /path/to/geckodriver` to install the built extension and exercise its Firefox UI, including real WebAuthn requests. Use `--chromedriver /path/to/chromedriver --chrome /path/to/chrome` for Chrome for Testing instead. It creates a test account, signs in two isolated CLI profiles, checks encrypted sync and RFC 6238 TOTP, checks server files for the plaintext password, restores a full backup and verifies access with the existing client, then tests deletion sync. Browser-enabled runs also verify passkey signatures from a fresh client and after backup recovery. It never modifies real vault data or global CLI configuration.

On Linux x86_64 with Node.js, npm and OpenSSL:

```sh
python3 tools/fetch-test-runtime.py
npm install --prefix .tools @bitwarden/cli@2026.10.0 --no-audit --no-fund
python3 tests/integration.py \
  --vaultwarden .tools/vaultwarden --web-vault .tools/web-vault \
  --bw .tools/node_modules/.bin/bw --library-path .tools/lib
```

The fetcher verifies the pinned OCI index, platform manifest and layer digests. A system compatible with the binary's other dynamic dependencies is still required. Production uses the complete image. The default integration proxy is a test fixture. To test real Caddy HTTPS/WebSocket forwarding, run `python3 tools/fetch-caddy-test-runtime.py` and add `--caddy .tools/caddy` to the integration command. The complete generated Compose stack also passed HTTPS, encrypted clients, passkeys, WSS and full backup/recovery in an isolated Docker VM. See [container acceptance and repeatable setup](docs/container-testing.md) for its scope and commands.


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
