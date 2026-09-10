#!/usr/bin/env bash
# Candidate mode validates locally; published mode also checks frozen manifests.
set -euo pipefail
candidate=false
if [[ ${1:-} == --candidate ]]; then
  [[ $# == 3 ]] || { echo 'usage: check_canonical.sh --candidate IMAGE_ID OUT' >&2; exit 1; }
  candidate=true; image_ref=$2; out=$3
  [[ $image_ref =~ ^sha256:[0-9a-f]{64}$ ]] || exit 1
else
  [[ $# == 2 ]] || { echo 'usage: check_canonical.sh GHCR_DIGEST OUT' >&2; exit 1; }
  image_ref=$1; out=$2
  [[ $image_ref =~ ^ghcr\.io/mamadou-wane/tvc-gold@sha256:[0-9a-f]{64}$ ]] || exit 1
  docker buildx imagetools inspect "$image_ref" --raw | python3 -c 'import json,sys; m=json.load(sys.stdin); assert "manifests" not in m and "config" in m, "platform manifest required"'
  docker pull --platform linux/amd64 "$image_ref"
fi
repo_root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$out"
out=$(cd "$out" && pwd)
[[ $(docker image inspect "$image_ref" --format '{{.Architecture}}') == amd64 ]] || exit 1
docker run --rm --pull=never --platform linux/amd64 --network=none --tmpfs /w/build:rw,exec \
  -v "$repo_root":/w:ro -v "$out":/e -w /w \
  -e TVC_GOLD_IMAGE="$image_ref" -e TVC_CANDIDATE="$candidate" \
  "$image_ref" bash -euo pipefail -c '
    cmake -S . -B /w/build -DCMAKE_BUILD_TYPE=RelWithDebInfo
    cmake --build /w/build -j
    /w/build/control_tests
    python3 -B tests/check_pid_corpus.py /w/build/control_tests
    /w/build/episode_tests
    /w/build/wire_tests
    /w/build/lockstep_tests
    python3 -B -m unittest tests.unit.test_headless tests.unit.test_trace tests.unit.test_control_ref tests.unit.test_episode_ref tests.unit.test_plant tests.unit.test_rng -v
    mode=()
    if [[ $TVC_CANDIDATE == true ]]; then mode=(--candidate-image-id "$TVC_GOLD_IMAGE"); fi
    python3 -B scripts/run_campaign.py --goldens --binary=/w/build/tvc_harness \
      --out=/e/goldens --manifest=/e/goldens.json "${mode[@]}"
    python3 -B scripts/run_campaign.py --goldens --validate --out=/e/goldens \
      --manifest=/e/goldens.json "${mode[@]}"
    python3 -B scripts/run_campaign.py --scenario=S2-gust --loss=0.30 --seeds=1-2 --delay-ticks=0,1 \
      --binary=/w/build/tvc_harness --out=/e/small --manifest=/e/small.json --check "${mode[@]}"
    python3 -B scripts/run_campaign.py --validate --out=/e/small --manifest=/e/small.json "${mode[@]}"
    if [[ $TVC_CANDIDATE == false ]]; then
      cmp /e/goldens.json tests/golden/lockstep/manifest.json
      for file in /e/goldens/diagnostic-csv/*.csv; do cmp "$file" "tests/golden/lockstep/$(basename "$file")"; done
      python3 -B scripts/run_campaign.py --scenario=S2-gust --loss=0.30 --seeds=1-8 --delay-ticks=0 \
        --binary=/w/build/tvc_harness --out=/e/loss-subset --manifest=/e/loss-subset.json --check
      python3 -B tests/functional/test_loss.py /e/loss-subset
      if [[ -f tests/golden/lockstep/campaign-v02b.json ]]; then
        python3 -B scripts/run_campaign.py --check-current
      fi
    fi
  '
