# Credlet extension source and reviewer build

This archive contains the readable Credlet extension sources, build script,
dependency lockfile, deterministic packager and unit tests. It includes no vault
state, account credentials, signing keys, test VM files or installed dependencies.
The desktop bridge is included only because one unit regression test exercises
the shared vault implementation through that bridge.

## Rebuild the submitted extension

Use Linux x64, Node **24.22.1** with its bundled npm, and Python **3.11.4+**.
Node's official archive and SHA-256 manifest are available at
https://nodejs.org/dist/v24.22.1/ . No compiler or private package registry is
required. Package dependencies and esbuild **0.28.2** are locked in
`package-lock.json` and fetched by npm with their integrity checks.

Extract this source ZIP into an empty directory and run from its root:

```sh
npm ci --no-audit --no-fund
npm test
npm run build
python3 tools/package-extension.py
```

Compare `extension/dist/credlet-firefox-0.2.0.xpi` with the **unsigned** submission
XPI. The Chrome ZIP can be compared in the same way. Output files have fixed ZIP
timestamps, modes and ordering. Mozilla adds signature files after submission, so
a signed XPI is not byte-identical to the unsigned input. Versioned output names
follow `package.json` when the extension version changes.

The source packager includes both this top-level README and its original
`extension/release/README.md` path so the same commands can recreate the reviewer
archive too. No generated code is manually patched after the build.

## Third-party code

All libraries are unmodified releases from the public npm registry. Their npm
declarations and exact integrity values are in `package.json`/`package-lock.json`:

- `hash-wasm` **4.12.0** supplies Argon2id, including its embedded WebAssembly:
  https://www.npmjs.com/package/hash-wasm/v/4.12.0 . Original source, including
  readable C/TypeScript, is at https://github.com/Daninet/hash-wasm . The npm
  package includes the C sources under `src/` and readable JS under `dist/`.
- `tldts` and `tldts-core` **7.4.19** supply public/private suffix validation:
  https://www.npmjs.com/package/tldts/v/7.4.19 and
  https://www.npmjs.com/package/tldts-core/v/7.4.19 . Original source is at
  https://github.com/remusao/tldts . Their npm packages include readable sources.
- `esbuild` **0.28.2** is a build dependency, not extension runtime code:
  https://www.npmjs.com/package/esbuild/v/0.28.2 .

The extension's `THIRD_PARTY_LICENSES.txt` contains runtime library licenses.
All runtime scripts, suffix data and WASM are packaged locally. The extension
does not download executable code or use an external KDF service.

## Functional review

Credlet requires a self-hosted Bitwarden-compatible HTTPS vault. The deployment
manager `credlet.py` and the project guide `SELF_HOSTING.md` are included for a
reviewer who wants to create a disposable single-owner Vaultwarden service.
That optional deployment needs Docker/Compose, a reachable HTTPS hostname and
its own temporary owner account. Do not use a real vault for review.

The extension's options page or toolbar popup accepts the server HTTPS origin,
owner email and master password. Its main functions are login creation/editing/
trash, explicit same-origin username/password/TOTP filling, and ES256 passkey
registration/sign-in. Every passkey approval requires the master password afresh.
An unsupported authenticator request can use the device provider instead, including while the vault is locked.

The `clipboardWrite` permission supports explicit **Copy** controls for usernames, passwords and codes. The extension never reads the clipboard. Icons are first-party assets; their editable SVG and pre-rendered PNG files are included in `extension/assets/`.

The self-hosted server receives the owner email, derived authentication data,
device identifier, encrypted vault records and ordinary connection metadata.
The master password is used locally. Filling releases the selected values to
the current matching website; passkey approval returns public ceremony data and
signatures to the requesting website. See `extension/release/privacy.md`.

The five-minute expiry and background termination lock the vault. Only the
server origin, owner email and random device identifier persist in extension
storage. Passkey private keys are never returned to the website or approval UI.
Firefox desktop/Android minimum is **142**. Actual Android UI/passkey acceptance
used Firefox Nightly; stable-channel signed installation still requires testing.

Build instructions follow Mozilla's source submission guidance:
https://extensionworkshop.com/documentation/publish/source-code-submission/ .
