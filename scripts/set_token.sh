#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"

read -s -p "Paste your GitHub token: " T
printf '\n'

if [ -z "$T" ]; then
  printf 'Token is empty.\n' >&2
  exit 1
fi

umask 077
printf 'GITHUB_TOKEN=%s\n' "$T" > "$root/.env"
chmod 600 "$root/.env"
unset T
printf 'Saved.\n'
