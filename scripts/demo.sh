#!/usr/bin/env bash
# Exact data reproduction uses the existing canonical image, never a rebuilt tag.
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"
if [[ -f /opt/tvc-gold/environment.json && -n ${TVC_GOLD_IMAGE:-} ]]; then
  exec python3 -B scripts/demo.py "$@"
fi
exec python3 - "$repo_root" "$@" <<'PY'
import json
import os
from pathlib import Path
import re
import sys

root=Path(sys.argv[1]).resolve()
args=sys.argv[2:]
image=json.loads((root/'tests/golden/lockstep/manifest.json').read_text())['toolchain']['image']
if not re.fullmatch(r'ghcr\.io/mamadou-wane/tvc-gold@sha256:[0-9a-f]{64}',image):
    raise SystemExit('demo: canonical platform digest required')
resolved=[]
explicit_binary=False
masked_output=False
index=0
while index<len(args):
    arg=args[index];key,separator,value=arg.partition('=')
    if key in ('--out','--gif','--binary'):
        if not separator:
            index+=1
            if index==len(args) or args[index].startswith('--'):
                raise SystemExit('demo: missing path for '+key)
            value=args[index]
        if not value:
            raise SystemExit('demo: empty path for '+key)
        try:
            relative=Path(value).resolve().relative_to(root)
        except ValueError:
            raise SystemExit('demo: host paths must remain inside the checkout: '+value)
        masked_output |= key in ('--out','--gif') and bool(relative.parts) and relative.parts[0]=='build'
        mapped=(Path('/w')/relative).as_posix()
        resolved.extend([key+'='+mapped] if separator else [key,mapped])
        explicit_binary |= key=='--binary'
    else:
        resolved.append(arg)
    index+=1
if masked_output and not explicit_binary:
    raise SystemExit('demo: output cannot be inside the temporary build mount')
command=['docker','run','--rm','--platform','linux/amd64','--network=none']
if not explicit_binary:
    command+=['--tmpfs','/w/build:rw,exec']
command+=['-v',str(root)+':/w','-w','/w','-e','TVC_GOLD_IMAGE='+image,
          image,'bash','scripts/demo.sh',*resolved]
os.execvp('docker',command)
PY
