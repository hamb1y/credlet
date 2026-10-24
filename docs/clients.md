# Client setup and acceptance

All clients use the same owner account and HTTPS server URL. [Bitwarden's self-hosted connection instructions](https://bitwarden.com/help/change-client-environment/) describe each client's server selector. Official downloads are at https://bitwarden.com/download/.

## Chrome and Firefox on desktop

Build and install the Credlet extension using [its setup guide](../extension/README.md), or install the official Bitwarden extension from the download page for upstream functionality. Credlet supports explicit ES256 passkey registration and sign-in; see its guide for current limits. Choose Self-hosted before signing in. Pin the extension and enable its autofill options. Save a login with the website's real HTTPS URI, visit that website and choose the matching login from the extension or its inline menu. Prefer user-triggered autofill; automatic page-load filling is optional.

For TOTP, edit a login and set its authenticator key to the service's secret or `otpauth://` URI. The client should display a rotating six-digit code. Check it against the service before discarding the old authenticator. See [integrated authenticator](https://bitwarden.com/help/integrated-authenticator/).

For Credlet passkeys, start registration or sign-in on the site, review the requesting origin in the Credlet approval tab, verify the master password, and approve. Choose **Use device instead** for native authenticators. For the official extension, enable passkey prompts in extension autofill settings. Register a passkey at the target site's account-security page and select Bitwarden as the provider. Sign out of the site, then sign back in using the saved passkey. Repeat on a second desktop/browser after syncing. These are stored website passkeys, distinct from using a passkey for vault login. See [passkey autofill](https://bitwarden.com/help/storing-passkeys/).

## Firefox on Android

The Credlet Firefox build declares `gecko_android`, uses a narrow-screen interface, and avoids desktop-only window APIs. Actual Android 15/Firefox Nightly 161 acceptance passed password creation/editing/trash, username/password/TOTP filling, passkey registration/assertion, lock, official-client sync and recovered-passkey signing. See [Android evidence and repeatable tests](android-testing.md) and [extension installation](../extension/README.md). Stable-channel signing/distribution and broader lifecycle checks remain outstanding.

The current official Bitwarden Firefox XPI (2026.10.0) declares only `browser_specific_settings.gecko` and its Mozilla API metadata lists only Firefox, without an Android target. A listing URL containing `/android/` redirects to the desktop listing and is not evidence of mobile support. The Credlet extension is being implemented to address that gap.

The native Android application passed self-hosted sign-in, vault sync, real app username/password autofill, TOTP display/paste, and system passkey creation/sign-in on the emulator. Its passkeys also passed independent signature checks, fresh-client sync and recovered-passkey signing. The Credlet extension separately passes desktop Firefox/Chrome and actual Android Firefox tests.

## Native Android app

Install Bitwarden from the official download page. Select Self-hosted, enter the server URL and sign in. In Android Settings, find Passwords, passkeys & autofill (wording varies by manufacturer), select Bitwarden as the preferred provider and enable the app's autofill service. Passkeys require an Android version supporting third-party passkey providers (Android 14+); see [upstream requirements](https://bitwarden.com/help/storing-passkeys/).

For native-app matching, save the app's `androidapp://package.name` URI on the login alongside any website URI. Tap a username/password field, choose Bitwarden, and select the matching login. Check both password creation and later filling. [Android autofill instructions](https://bitwarden.com/help/auto-fill-android/) cover system and accessibility options. Accessibility permissions are needed only if choosing that fallback.

Test a native app login, a browser login, a TOTP code, and passkey registration/authentication. Sync, lock and unlock the app, then repeat authentication to prove the passkey survived.

## Linux, Windows and macOS applications

Install the official desktop app using the download page's OS-specific installer or package. Select the self-hosted server, sign in and verify the same item appears on all three platforms. Configure a vault lock timeout and clipboard-clearing timeout. For browser biometric unlock, enable desktop browser integration and follow the platform-specific client instructions.

For native-app filling, run the [Credlet desktop companion](../desktop/README.md). Capture the target field, review its executable/application identity, explicitly link a login and fill the selected username, password or code. Standalone Linux and Windows bundles passed this through their actual frozen interfaces and real GTK/Win32 fields. The macOS adapter is implemented but still needs a build and platform acceptance. Browser passkey use is handled by the extension, and Android passkey use by the Android provider.

## Acceptance record

Use disposable service accounts for these checks; record client version, OS/browser version and date alongside your test report.

1. Create one login, sync to a second target, fill and submit on a matching site/app.
2. Change its password, sync, and confirm the other target fills the new value.
3. Add a TOTP seed and confirm the displayed six-digit code is accepted by its service.
4. Register a website passkey, sync, then authenticate from another supported target.
5. Lock the vault and verify access requires unlock; unlock and repeat filling.
6. Delete the fixture, sync, and verify it disappears on the second target.

Browser/provider tests must actually perform WebAuthn registration and authentication. Storing a field named `passkey` or passing a server API test does not prove that integration.
