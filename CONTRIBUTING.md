# Contributing

Open an issue with a reproducible example or send a focused pull request.
Use disposable accounts and fixtures for development. Follow [SECURITY.md](SECURITY.md)
for vulnerabilities.

Run the checks in the [testing guide](docs/testing.md) for the code you change.
Release automation builds Windows and Linux bundles and tests their actual
frozen executables. Keep the version in `package.json` as the source of truth;
release tags are `vVERSION`. Keep dependency versions and action commits pinned.

Do not commit state directories, vault exports, signing credentials, installed
dependencies or test VM images. The extension reviewer archive uses an explicit
source allowlist; update it when a change adds required build inputs.

By contributing, you agree that your original contributions are licensed under
the repository's MIT license. Preserve upstream license notices.
