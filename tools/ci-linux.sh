#!/bin/sh
# Native release checks inside the pinned Ubuntu 22.04 build environment.
set -eu
cd /work
python -m unittest discover -s tests -v
sh desktop/linux/build.sh
python tools/build-server.py
python tools/smoke-server.py server/dist/credlet-server
python tools/smoke-desktop.py desktop/dist/Credlet/Credlet
python tests/native_linux.py
