# Lockbox browser extension

This client connects directly to the single-user Vaultwarden service. Builds target Chrome (Manifest V3) and Firefox on desktop and Android (Manifest V2 with `gecko_android`, minimum Firefox 142).

Implemented: master-password sign-in, PBKDF2 and Argon2id vaults, vault login TOTP, encrypted login creation/editing/trash and synchronization, search, password generation, TOTP display and filling, password reveal, user-triggered page filling, WebAuthn passkeys, and lock. Master passwords, tokens, decrypted vaults and keys are never written to extension storage. Only the server URL, email and random device identifier persist. An absolute five-minute deadline locks the vault; browser background-process termination also locks it. No refresh token is retained.

The interface uses touch-sized controls and adapts to narrow screens. Actual Android 15/Firefox Nightly 161 acceptance passed password/TOTP filling and WebAuthn passkeys, including encrypted sync and backup recovery. See [Android test evidence and setup](../docs/android-testing.md). Stable-channel signing/distribution remains outstanding.

## Build and install

From the project root, use Node.js 24.22.1 and Python 3.11.4+:

```sh
npm ci
npm test
npm run build
python3 tools/package-extension.py
```

In desktop Firefox, open `about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on**, and select `extension/dist/firefox/manifest.json`. Temporary installations last until Firefox exits. The same files are packaged as `extension/dist/lockbox-firefox-0.1.0.xpi`.

In Chrome, open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked**, and select `extension/dist/chrome`. The ZIP artifact can be used as an upload package. Store signing/distribution has not been performed.

Packaging also creates `extension/dist/lockbox-extension-source-0.1.0.zip`, adjacent SHA-256 files and `release.json`. A clean source rebuild passed all 12 Node tests and reproduced the Firefox XPI, Chrome ZIP and source ZIP byte for byte. See [signing and distribution](../docs/extension-distribution.md) for the reviewer sources, privacy disclosure and installation steps.

For Android development, use a Firefox build that permits developer addon installation and Android remote debugging. Release Firefox requires Mozilla signing; a signed unlisted XPI can be installed from a file on Android, without a public listing. The current package is unsigned. See [Mozilla's file-installation guide](https://extensionworkshop.com/documentation/publish/install-self-distributed/). This project does not claim that a manifest declaration alone proves mobile functionality.

## Use

Open the extension on the HTTPS page you want to fill. Set the server to your own vault's HTTPS origin, sign in with the owner email and master password, and supply the vault's authenticator code if enabled. Select a saved login, then choose **Fill current page**. The extension checks the current URL again and the content script checks the origin at the moment it fills. It fills only visible fields in the top frame and never submits the form. It rejects cross-origin form actions.

Use **Add login** to save a generated or existing password and an optional base32 or `otpauth://totp` seed. New login URIs use the site's exact HTTPS origin. Synced URI rules never expand to a different origin; imported regex and Never-match rules do not authorize filling. Same-origin matching is intentionally narrower than Bitwarden's domain matching. Add each legitimate origin separately using the web vault if needed.

For a code field, choose **Fill code** in the login detail. The extension fills an unambiguous visible field marked `one-time-code` or a recognized authenticator-code field. **Edit** updates the selected login while preserving its existing passkeys, attachments, custom fields, item encryption key and additional URIs. **Trash** asks for confirmation and moves the login to the server's recoverable trash.

## Passkeys

Start passkey creation or sign-in on an HTTPS site's normal account page. Lockbox opens an approval tab showing the actual requesting origin and relying-party ID. Unlock the vault if necessary, select an account for sign-in, then enter the master password and approve. Every operation verifies the master password afresh. The page receives registration public data or a signed assertion; the private key stays encrypted in the vault and is decrypted only inside the extension background process.

The current provider supports ES256/P-256, discoverable and allow-list credentials, and synchronizable passkeys with a zero signature counter. It verifies the RP ID against the browser-authenticated sender origin and the public suffix list, including private suffixes. Requests must originate in the active top-level page. Navigating away, aborting, closing approval or timing out cancels the request. Maximum approval time is two minutes.

Choose **Use device instead** to invoke the browser's original authenticator. Unsupported public-key algorithms, external authenticators and direct/enterprise attestation also use the native path. Conditional mediation uses the native browser implementation; Lockbox currently uses explicit approval tabs. Cross-origin frames and advanced extensions such as PRF are not implemented by this provider. Lockbox's provider passed real Android Firefox registration/assertion; native Android fallback and broader third-party website compatibility still need acceptance testing.

Only individual logins are shown. Organization items and deleted items are excluded. Items configured to require a master-password re-prompt must be managed using the web vault. Other vault login two-factor methods, offline unlock and automatic save prompts remain to be added. Official clients remain available for those vault-management features while implementation continues.

## Verification

`npm test` checks independent key-derivation and cipher interoperability, authentication-tag rejection, RFC 6238 vectors, origin matching, key wiping on expiration, preservation of imported cipher metadata during edits, public-suffix rejection and independent Node verification of passkey registration and assertion signatures.

`tests/integration.py` uses the real extension vault code to read a login encrypted by the official Bitwarden CLI, save another encrypted login and verify the CLI can decrypt it. The `--kdf argon2` option also proves interoperability with an Argon2id account.

With `--geckodriver /path/to/geckodriver`, the same test installs the actual built Firefox extension, trusts its disposable certificate only inside the temporary browser profile, and drives its UI. Geckodriver's `--allow-system-access` is used solely for WebDriver access to extension documents; it is not a product setting.

For Chrome for Testing, use `--chromedriver /path/to/chromedriver --chrome /path/to/chrome` instead. The test exercises both browsers' real credential API, wrong-password rejection, cancellation and AbortSignal handling. An independent relying-party verifier checks attestation data, origin, challenge, RP ID hash, user-verification flags, public key and assertion signature. Chrome also exercises **Use device instead** against a WebDriver CTAP2 virtual authenticator. The full integration checks that another freshly unlocked client can sign using the synchronized passkey, the official CLI can decrypt its record, and backup recovery preserves it.

Dependencies are pinned in the root lockfile. Bundles include the licenses for hash-wasm, tldts and tldts-core; Web Crypto supplies AES-CBC, HMAC and PBKDF2. hash-wasm supplies Argon2id. No runtime script or WASM is fetched from a CDN.
