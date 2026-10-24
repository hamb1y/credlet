# Browser extension distribution

The Firefox and Chrome development packages are built locally. Firefox's current
XPI is **unsigned**. Signing/upload has not been performed. The source archive
and local verification below prepare a submission; they do not establish Mozilla
approval or stable-channel installation.

## Build and verify packages

```sh
npm ci
npm test
npm run build
python3 tools/package-extension.py
python3 tools/verify-extension-rebuild.py
```

The packager creates Firefox/Chrome packages, matching reviewer sources,
adjacent SHA-256 files and `extension/dist/release.json`. It rejects unexpected
or missing payload files, symlinks and mismatched versions. Source inputs use
an explicit allowlist and exclude vault state, credentials and VM files.
The clean-source verifier extracts into a fresh directory, runs all 12 Node
tests, rebuilds and compares all three archives byte for byte.

[GitHub Releases](https://github.com/hamb1y/credlet/releases/latest) publishes
these build outputs with explicit signing status. `SHA256SUMS` and
`release-manifest.json` are the authoritative checksums for each release.
The Firefox unsigned input is named `credlet-firefox-VERSION-unsigned.xpi` in
release assets; local packaging retains `credlet-firefox-VERSION.xpi` for AMO
submission. A signed XPI, when available, is a separate `-signed.xpi` asset.

The [release workflow](../.github/workflows/release.yml) also runs pinned Mozilla
addons-linter 10.14.0 and the clean reviewer-source verification on every build.
See [release automation](releases.md) to configure optional signing secrets.

Mozilla requires matching readable sources and rebuild instructions for bundled
code. See its [source submission guide](https://extensionworkshop.com/documentation/publish/source-code-submission/)
and [third-party library guidance](https://extensionworkshop.com/documentation/publish/third-party-library-usage/).

## Firefox signing for self-distribution

Mozilla signing is required for release/beta installation. A public AMO listing
is optional: an **unlisted** submission returns a signed XPI for self-distribution.
See [Mozilla's signing overview](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/).

Use your Mozilla Developer Hub account. In its new-submission flow choose
**On your own**, upload `credlet-firefox-0.2.0.xpi`, and attach
`credlet-extension-source-0.2.0.zip` when asked for source code. Select Firefox
desktop and Android compatibility. The package declares minimum **142** on both.
The source ZIP's README and `extension/release/amo-metadata.json` supply build and
reviewer notes; provide the privacy disclosure if requested. Download the signed
version from the submission after it is approved.

An account owner can instead use web-ext **10.8.0**. Obtain the JWT issuer and
secret from the [Developer Hub credentials page](https://addons.mozilla.org/developers/addon/api/key/)
and supply them locally as `WEB_EXT_API_KEY` and `WEB_EXT_API_SECRET`. Keep their
values out of command arguments, source files and archives. With those variables
configured, this command uploads the built files and source ZIP for **unlisted**
signing:

```sh
npm exec --yes --package=web-ext@10.8.0 -- web-ext sign \
  --no-config-discovery --no-input --channel unlisted \
  --amo-base-url https://addons.mozilla.org/api/v5/ \
  --source-dir extension/dist/firefox \
  --artifacts-dir extension/dist/signed \
  --upload-source-code extension/dist/credlet-extension-source-0.2.0.zip \
  --amo-metadata extension/release/amo-metadata.json
```

The command's flags were checked against installed web-ext **10.8.0**; no signing
credentials were configured and it was not run against AMO. See the official
[web-ext command reference](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/).
If approval remains pending, inspect that submission in the Developer Hub before
attempting another upload. The signed output is a distinct artifact; keep the
unsigned input/source checksums with it.

The display name is Credlet. The add-on ID remains `lockbox@selfhost.local` for upgrade compatibility. Keep the same ID and signing account
for updates, and increment `package.json`'s version before rebuilding. There is
no self-hosted update manifest configured; self-distributed updates are installed
manually. The local unsigned packager does not overwrite `extension/dist/signed`.

## Install the signed Firefox package

Desktop Firefox: save the signed XPI, open **Add-ons and themes**, then the
settings cog's **Install Add-on From File**. Choose the XPI and accept the
installation prompt.

Android Firefox: save the signed XPI on the device, open **Settings → About
Firefox**, and tap the Firefox logo five times. Return to Settings, choose
**Install Extension from File**, select the XPI and accept the prompt. These are
[Mozilla's file-installation instructions](https://extensionworkshop.com/documentation/publish/install-self-distributed/).

Verify installation and vault use on a disposable release-channel profile/device,
including a browser restart, before claiming stable-channel acceptance. Actual
Android functional tests so far used temporary installation on Nightly.

## Chrome

For local desktop use, open `chrome://extensions`, enable Developer mode and
load the unpacked `extension/dist/chrome` directory. The ZIP is the store upload
input; store publication has not been performed. Website permissions and features
are described in [extension setup](../extension/README.md).
