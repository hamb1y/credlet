# Android acceptance environment

Firefox Nightly **161.0a1** on an actual Android **15 / API 35** x86_64 emulator passed the Lockbox extension UI and full HTTPS/Argon2id interoperability/recovery run. This is an Android browser, not a resized desktop window. The extension was installed temporarily through geckodriver; stable-channel signing and distribution remain outstanding.

The official Bitwarden **2026.10.0** F-Droid APK also passed native self-hosted sign-in, decrypted vault sync, username/password autofill, independently checked TOTP display, and explicit TOTP paste into a native code field. Complete Android system passkey-provider registration/sign-in, fresh-client sync and recovered-passkey signing passed on the Google APIs image described below.

## Start the isolated device

On Linux x64 with working KVM, Python, Node, npm, OpenSSL, NSS `certutil`, and the test runtime prerequisites from the project README:

```sh
python3 tools/fetch-android-test-runtime.py
python3 tools/fetch-android-test-apps.py
python3 tools/android-test-device.py start
python3 tools/android-test-device.py status
```

Wait until status reports `"booted": true`. All device data, ADB keys, SDK archives and logs live under ignored `.tools/`. The controller runs a headless AOSP API 35 image with KVM and a private ADB server on port **5038**. A loopback relay on **5037** supports geckodriver's fixed ADB port. It refuses occupied ports and does not stop an existing service. The emulator serial is **emulator-5580**. Commands below name that serial explicitly.

Google SDK stable-channel pins: emulator **37.2.12**, platform-tools **37.0.1**, build-tools **35.0.0**, platform API **35 r2**, AOSP x86_64 image **35 r2**. The fetcher checks the upstream repository's published SHA-1 values and records SHA-256 digests. Bitwarden's APK pin matches its GitHub release asset digest. Firefox's pin records the SHA-256 of the APK retrieved from Mozilla's HTTPS archive; it is not a separately verified upstream checksum publication. Upstream SDK/APK licenses apply; these test runtimes are not included in Lockbox's distributions.

```sh
.tools/android-sdk/platform-tools/adb -P 5038 -s emulator-5580 install .tools/android-apps/firefox-nightly-161.apk
.tools/android-sdk/platform-tools/adb -P 5038 -s emulator-5580 install .tools/android-apps/bitwarden-2026.10.0.apk
```

## Run the browser acceptance

Build/package the extension first as described in its README, then supply geckodriver **0.37.1** and the pinned server, Caddy and CLI runtimes:

```sh
python3 tests/integration.py \
  --vaultwarden .tools/vaultwarden --web-vault .tools/web-vault \
  --library-path .tools/lib --bw .tools/node_modules/.bin/bw \
  --caddy .tools/caddy --kdf argon2 --geckodriver .tools/geckodriver \
  --android-package org.mozilla.fenix --android-serial emulator-5580 \
  --adb .tools/android-sdk/platform-tools/adb --adb-port 5038 \
  --browser-screenshot .tools/firefox-android.png
```

The harness uploads a fresh Firefox profile containing only its temporary test CA, reverses the local HTTPS port to the emulator, installs the extension temporarily, and dismisses Firefox's setup/install prompts through native Android controls. TLS validation remains enabled. The profile and server are disposable; the test never uses real vault credentials.

Verified: password creation/editing/trash, exact-origin filling, foreign form-action rejection, six-digit display/fill, actual website passkey creation/assertion, wrong-master rejection, approval/cancel/AbortSignal/RP checks, private storage and lock. An independent verifier checks the WebAuthn signatures. The full run also checks official-client FIDO2 decryption, a fresh client's signing, authenticated WSS delivery, full backup recovery and recovered-passkey signing. `--browser-only` skips CLI and recovery checks for faster UI debugging.

The screenshots show the actual mobile extension and approval page at `.tools/firefox-android.png` and `.tools/firefox-android-passkey.png`. They are fixture accounts. The emulator retains its installed apps between runs, while the browser test profile and server account are recreated each time.

## Run native application acceptance

Build the small native relying app with a JDK and the pinned SDK. It contains real Android username/password/code fields and writes inspected fixture values only to its private app directory. The test reads those values through `run-as`; it does not add inspection endpoints to the password manager.

```sh
python3 tools/build-android-fixture.py --java-home /path/to/jdk-21
.tools/android-sdk/platform-tools/adb -P 5038 -s emulator-5580 root
.tools/android-sdk/platform-tools/adb -P 5038 -s emulator-5580 wait-for-device
python3 tests/integration.py \
  --vaultwarden .tools/vaultwarden --web-vault .tools/web-vault \
  --library-path .tools/lib --bw .tools/node_modules/.bin/bw \
  --caddy .tools/caddy --android-native \
  --adb .tools/android-sdk/platform-tools/adb --adb-port 5038
```

This resets only the official client and fixture on the named disposable emulator. It temporarily installs the integration CA into Android's **user** trust store and reverses the local HTTPS port. The upstream client's self-hosted network-security configuration trusts user CAs; certificate validation stays enabled. Normal cleanup removes that CA, the port reverse, and the fixture's inspected fields. No host trust store or physical device is modified. The tested compiler was Temurin **21.0.13+9**; fixture SDK/build-tools are API **35**/**35.0.0**.

The native app must decrypt the CLI-created login and display the independently calculated RFC 6238 code. Android's standard Autofill service fills actual `EditText` username/password fields for the saved `androidapp://org.lockbox.fixture` URI. Bitwarden copies the TOTP after filling; an explicit **Paste code** action checks that value in the native code field. This is a paste flow, not automatic code-field detection. A code copied just before a 30-second rollover is checked against its autofill interval.

The harness focuses the username field and waits for the keyboard before requesting autofill. Its shell-only `UiDump` helper reads all accessibility windows, including Gboard's inline suggestion area, instead of only the application's active window. It is run through test ADB and is not a component or endpoint in the password manager. Native password/TOTP acceptance also passed on the Google APIs image with Gboard.

Add `--android-native-driver .tools/geckodriver` to exercise the Android system passkey provider through Firefox's built-in WebAuthn API in a fresh profile **without the Lockbox extension**. The complete run passed on the Google APIs image. The harness handles native save/approval controls and uses the independent relying-party verifier. It resets Android's credential-selector UI before a new test to remove tasks left by interrupted driver sessions. After a provider activity closes, it waits for Firefox focus, taps the visible native page button and confirms that its actual JavaScript handler ran.

The passkey fixture uses `vault.test` with Firefox's `network.dns.localDomains` loopback override and a matching trusted certificate. Registration and sign-in both passed after fresh master verification. Independent checks include the exact upstream Bitwarden SDK AAGUID `d548826e79b4db40a3d811116f7e8349`, challenge/origin/RP binding, flags, COSE/SPKI public key, credential ID and assertion signature. Android Firefox omits optional `credProps`; the successful assertion without a credential ID proves discoverability directly. Firefox first queries Google Play Services, which the AOSP-only image lacks. The optional Google APIs image is pinned to API **35 x86_64 r9**, upstream SHA-1 `0103e6dab21290c4b9d16550a3ce99476f884eef`:

```sh
python3 tools/fetch-android-test-runtime.py --google-apis
python3 tools/android-test-device.py stop
python3 tools/android-test-device.py start --image google-apis
python3 tools/android-test-device.py status
```

It has a separate AVD data directory and requires installing the two pinned APKs again. Wait for boot, install the APKs as above, and enable test ADB root before running native acceptance. The controller refuses to switch images while a device is running. Run the native command above with `--android-native-driver .tools/geckodriver` after this setup.

That full integration passed native password/TOTP filling, both system-provider passkey ceremonies, independent signatures, a newly unlocked client's signing, official CLI FIDO2 decryption, server-file plaintext/private-key scans, authenticated WSS delivery, complete backup/restore, recovered-passkey signing and deletion sync. The public ceremony is saved with mode `600` at `.tools/android-test/native-provider-public.json`; it contains no private key or master password. The result establishes this emulator and Nightly combination; physical devices and stable distribution still need broader acceptance.

Stop the device when finished:

```sh
python3 tools/android-test-device.py stop
```

The controller stops only its own emulator, foreground ADB process and relay. Its status checks live processes and the emulator's boot property rather than treating a state file as proof of activity.
