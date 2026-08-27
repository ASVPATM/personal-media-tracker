#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$project_dir"

pmt_version=beta
if [ -f PMT_SERVER_VERSION ]; then
  pmt_version=$(sed -n '1p' PMT_SERVER_VERSION)
fi
compose() { PMT_VERSION="$pmt_version" docker compose "$@"; }

local_health() {
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1
}

files="-f compose.yaml"
if grep -q '^WATCHTRACKER_DATABASE_URL_OVERRIDE=postgresql' server.env 2>/dev/null; then
  files="$files -f compose.postgres.yaml"
fi

case "${1:-status}" in
  start)
    compose $files up -d --wait --wait-timeout 180
    if local_health; then
      printf '%s\n' "PMT Server Beta is healthy locally. Keep Tailscale connected for private device access."
    else
      printf '%s\n' "PMT Server started, but its local health check failed. Run: $0 logs" >&2
      exit 1
    fi
    ;;
  stop) compose $files stop ;;
  status)
    compose $files ps
    if local_health; then
      printf '%s\n' "Local PMT health: ready"
    else
      printf '%s\n' "Local PMT health: unavailable (start the server or inspect logs)"
    fi
    tailscale_bin=""
    if command -v tailscale >/dev/null 2>&1; then
      tailscale_bin=$(command -v tailscale)
    elif [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then
      tailscale_bin=/Applications/Tailscale.app/Contents/MacOS/Tailscale
    fi
    if [ -n "$tailscale_bin" ]; then
      "$tailscale_bin" serve status || printf '%s\n' "Tailscale Serve: unavailable (open Tailscale and confirm it is connected)"
    fi
    ;;
  logs) compose $files logs --tail=200 tracker ;;
  backup)
    compose $files exec tracker personal-media-tracker backup
    ;;
  recover-server-account)
    printf '%s\n' "This host-only recovery changes the server-account password and signs that account out everywhere."
    printf '%s\n' "Regular-user accounts and every media library remain unchanged."
    compose $files exec tracker personal-media-tracker recover-server-account
    ;;
  finish-setup)
    if ! compose $files exec -T tracker personal-media-tracker server-readiness |
      grep -q '"owner_configured": true'; then
      printf '%s\n' "Finish creating the server account in your browser, then run this again." >&2
      exit 1
    fi
    temporary_env="server.env.finish-setup.$$"
    trap 'rm -f "$temporary_env"' EXIT HUP INT TERM
    grep -v '^WATCHTRACKER_SERVER_BOOTSTRAP_TOKEN=' server.env > "$temporary_env"
    chmod 600 "$temporary_env"
    mv "$temporary_env" server.env
    trap - EXIT HUP INT TERM
    compose $files up -d --force-recreate tracker
    printf '%s\n' "One-time setup code removed. PMT Server Beta is ready for testing."
    ;;
  *) printf '%s\n' "Usage: $0 status|start|stop|backup|logs|recover-server-account|finish-setup" >&2; exit 2 ;;
esac
