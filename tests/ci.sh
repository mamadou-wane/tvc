#!/usr/bin/env bash
# Functional gate. Runs inside the tvc-dev container. Never a timing source.
set -euo pipefail
cmake -S . -B build && cmake --build build -j
if [ -d tests/unit ]; then python3 -m unittest discover -s tests/unit -v; fi
if [ -d tests/functional ]; then
  TVC_BIN="$PWD/build/tvc_harness" python3 -m unittest discover -s tests/functional -v
fi
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-sanitize-recover=all"
cmake --build build-asan -j
if [ -d tests/functional ]; then
  TVC_ASAN=1 TVC_BIN="$PWD/build-asan/tvc_harness" python3 -m unittest discover -s tests/functional -v
fi
echo "ci.sh: all green"
