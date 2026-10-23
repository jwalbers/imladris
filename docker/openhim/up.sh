#!/usr/bin/env bash
# OpenHIM + the AdvaPACS mediator for the lab, from PIH's openmrs-contrib-distro-tools
# fragments (the same ones Kol-CI runs), unchanged. Lab settings in .env override the
# fragments' *.env.defaults. sso-gate.yaml (lab-only) puts the PIH sign-in in front of the console.
#
#   ./up.sh            # start / update
#   ./up.sh ps|logs|down …   # any other docker compose command
set -euo pipefail
cd "$(dirname "$0")"
DT="${DISTRO_TOOLS:-$HOME/git/PIH/openmrs-contrib-distro-tools}"
S="$DT/docker/services"
# Compose resolves relative paths against the first -f file's directory (distro-tools), so
# sso-gate.yaml gets this checkout's docker/ dir as an absolute path.
export IMLADRIS_DOCKER_DIR="$(cd .. && pwd)"
[ -f .env ] || { echo "create .env from .env.example first" >&2; exit 1; }
compose=(docker compose -p openhim
  --env-file "$S/openhim.env.defaults" --env-file "$S/openhim-advapacs-mediator.env.defaults" --env-file .env
  -f "$S/openhim.yaml" -f "$S/openhim-advapacs-mediator.yaml" -f sso-gate.yaml)
if [ $# -eq 0 ]; then "${compose[@]}" up -d; else "${compose[@]}" "$@"; fi
