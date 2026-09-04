#!/usr/bin/env bash
# Functional gate. Runs inside the tvc-dev container. Never a timing source.
set -euo pipefail
# Style gate: no em dashes in code or console output.
if grep -rn $'\xe2\x80\x94' src scripts tests \
    --include='*.cpp' --include='*.hpp' --include='*.py' --include='*.sh'; then
  echo "ci.sh: em dashes found in the files above"; exit 1
fi
# Public-path gate: no tracked document points at a gitignored path.
python3 scripts/check_public_paths.py
cmake -S . -B build && cmake --build build -j
./build/wire_tests
./build/rt_setup_tests
./build/env_probe_tests
./build/ring_stress
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
./build-asan/wire_tests
./build-asan/rt_setup_tests
./build-asan/env_probe_tests
./build-asan/ring_stress
cmake -S . -B build-tsan -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS="-fsanitize=thread"
cmake --build build-tsan --target ring_stress -j
./build-tsan/ring_stress
echo "ci.sh: all green"
