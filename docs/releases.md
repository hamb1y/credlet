# Releases

The [Build and release workflow](../.github/workflows/release.yml) runs for main,
pull requests, version tags and manual dispatch. Main/PR/manual runs produce
downloadable Actions artifacts. A matching `vVERSION` tag publishes a GitHub
Release only after every build and check succeeds.

## Assets

Each release includes Windows/Linux x64 desktop and server-management archives,
Chrome ZIP, an explicitly named unsigned Firefox XPI, extension reviewer-source
ZIP, per-file checksums, native build metadata, `release-manifest.json` and
`SHA256SUMS`. A signed Firefox XPI is added when signing is configured.
The server tool requires Docker; it manages pinned Linux containers on both OSes.

Linux binaries are built in the digest-pinned Ubuntu 22.04 container with glibc
2.35. Windows binaries are built on Windows Server 2025 with Python 3.14.8.
The desktop runtime includes verified Node 24.22.1. Native archives are built on
their target OS; their byte identity is not claimed across independent builds.
The extension archives are rebuilt from their reviewer sources and compared
byte for byte in every workflow run.

## Verify a download

Download `SHA256SUMS` alongside the selected archives. Linux, after downloading
all listed assets:

```sh
sha256sum --check SHA256SUMS
```

For one downloaded file, compare its `sha256sum filename` output to the matching
line. Windows PowerShell:

```powershell
Get-FileHash .\lockbox-desktop-0.1.0-win-x64.zip -Algorithm SHA256
```

Checksums detect corruption; obtain both files and checksums from the intended
GitHub release. Native binaries are currently not code-signed.

## Publish a version

1. Update `package.json` and the root version in `package-lock.json` together;
   `npm install --package-lock-only --ignore-scripts` updates the lockfile.
2. Update documentation examples and run the checks. Merge to main and let its
   Windows/Linux/extension jobs pass.
3. Tag the reviewed commit and push:

   ```sh
   git tag v0.1.0
   git push origin v0.1.0
   ```

The workflow rejects a tag that differs from `package.json`. The publisher
requires the complete expected asset set and validates checksums and native
build metadata before publishing. Build jobs have read-only repository access;
only the final publish job receives `contents: write`. Actions are pinned to
commit SHAs and checked-out build code does not retain Git credentials.

The workflow will not overwrite an existing release. Publish a new version for
corrected public assets. Assets upload to a draft first; publication happens
only after every upload completes. An interrupted upload leaves a draft for
the maintainer to inspect before retrying. Manual dispatch builds candidates without creating a
release. No macOS job or binary is included while platform work is deferred.

## Optional Firefox signing

Configure repository Actions secrets `WEB_EXT_API_KEY` and `WEB_EXT_API_SECRET`
from your Mozilla Developer Hub account. On version tags, CI submits an
**unlisted** signing request with the matching reviewer sources using pinned
web-ext 10.8.0. Both secrets are required when either is present. Pull requests
and main builds do not submit signing requests.

Without credentials, CI publishes only the clearly labeled unsigned development
XPI. With credentials, a failed/pending signing request fails the job rather
than silently calling an unsigned file signed. Check the Developer Hub before
retrying a pending submission. The signed package is checked for its expected
version, add-on ID and Mozilla signature files, then published separately.
See [extension distribution](extension-distribution.md) for installation steps.
