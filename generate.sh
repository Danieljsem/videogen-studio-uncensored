#!/usr/bin/env bash
# Command line: ./generate.sh image.jpg "prompt" [--res 720] [--sec 5]   (image -> video)
#               ./generate.sh --image "prompt" [--aspect 16:9] [--count 4]   (text -> image)
# GPU settings come from local.env (written by install.sh).
cd "$(dirname "$(readlink -f "$0")")"
export PYTHONUTF8=1
if [ "${1:-}" = --image ]; then shift; exec venv/bin/python generate_image.py "$@"; fi
exec venv/bin/python generate.py "$@"
