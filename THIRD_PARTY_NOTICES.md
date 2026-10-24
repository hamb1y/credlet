# Third-party software

Lockbox's first-party code is MIT licensed. Dependencies retain their own
licenses; MIT does not relicense upstream servers, clients or bundled runtimes.

| Component | Use | License / source |
| --- | --- | --- |
| Vaultwarden | Containerized vault server; downloaded separately by Docker | [AGPL-3.0](https://github.com/dani-garcia/vaultwarden) |
| Caddy | Containerized HTTPS proxy; downloaded separately by Docker | [Apache-2.0](https://github.com/caddyserver/caddy) |
| Bitwarden clients | Optional separately installed clients | [Upstream licenses](https://github.com/bitwarden/clients) |
| hash-wasm | Bundled Argon2id implementation | [MIT](https://github.com/Daninet/hash-wasm) |
| tldts / tldts-core | Bundled extension public suffix rules | [MIT](https://github.com/remusao/tldts) |
| Node.js | Bundled desktop runtime | [Node.js and third-party licenses](https://github.com/nodejs/node/blob/main/LICENSE) |
| CPython | Bundled desktop / server-tool runtime | [PSF and incorporated licenses](https://github.com/python/cpython/blob/main/LICENSE) |
| PyInstaller | Binary packaging and bootloader | [GPL-2.0 with bootloader exception](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt) |
| Tcl/Tk | Desktop interface | [Tcl/Tk licenses](https://www.tcl-lang.org/software/tcltk/license.html) |
| PyGObject, GLib, GTK and AT-SPI | Linux desktop integration | LGPL; installed distribution copyright files accompany Linux bundles |
| comtypes | Windows desktop accessibility binding | [MIT](https://github.com/enthought/comtypes) |

Extension packages contain the complete runtime JavaScript library license texts
in `THIRD_PARTY_LICENSES.txt`. Desktop bundles include Node's combined `LICENSE`
and the bridge's library notices under `_internal/runtime/`. Desktop and server
archives also include `third-party-licenses/`, with Python, PyInstaller and
available platform dependency copyright/license files. Libraries are used
without local modifications. The matching Lockbox source and build recipes are
available in the release's Git tag; upstream sources are linked above.
