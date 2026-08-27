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

say() { printf '\n%s\n' "$1"; }
fail() { printf '\nSetup stopped: %s\n' "$1" >&2; exit 1; }

wait_for_private_https() {
  check_url=$1
  attempts=0
  while [ "$attempts" -lt 30 ]; do
    if curl --fail --silent --show-error --max-time 5 "$check_url/health" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done
  return 1
}

say "Personal Media Tracker Server Beta — easy setup"
printf '%s\n' "This optional beta creates a private home server. Your library stays on this computer."
printf '%s\n' "Keep verified backups and update to each new server beta while testing."

command -v docker >/dev/null 2>&1 || fail "Install and open Docker Desktop, then run this installer again."
compose version >/dev/null 2>&1 || fail "Docker Compose is unavailable. Update Docker Desktop and try again."

if [ -f server.env ]; then
  say "An existing PMT Server setup was found. Its private settings will not be replaced."
  printf '%s' "Start the existing server now? [Y/n] "
  IFS= read -r existing_choice
  case "$existing_choice" in
    n|N|no|NO) say "Nothing was changed."; exit 0 ;;
    *) exec "$script_dir/pmt-server-control.sh" start ;;
  esac
fi

tailscale_bin=""
if command -v tailscale >/dev/null 2>&1; then
  tailscale_bin=$(command -v tailscale)
elif [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then
  tailscale_bin=/Applications/Tailscale.app/Contents/MacOS/Tailscale
fi

server_url=""
if [ -n "$tailscale_bin" ] && command -v python3 >/dev/null 2>&1; then
  tailscale_status=$("$tailscale_bin" status --json 2>/dev/null || true)
  dns_name=$(
    printf '%s' "$tailscale_status" |
      python3 -c 'import json,sys; print((json.load(sys.stdin).get("Self") or {}).get("DNSName", "").rstrip("."))' 2>/dev/null || true
  )
  if [ -n "$dns_name" ]; then
    server_url="https://$dns_name"
    say "Tailscale found: $server_url"
  elif [ -x "$tailscale_bin" ]; then
    fail "Open Tailscale and confirm it says Connected, then run this installer again."
  fi
fi

if [ -z "$server_url" ]; then
  say "Paste the private HTTPS address shown by Tailscale Serve."
  printf '%s' "PMT Server address (https://…): "
  IFS= read -r server_url
fi

case "$server_url" in
  https://*.*) ;;
  *) fail "The server address must be a complete private HTTPS address." ;;
esac
server_url=${server_url%/}
trusted_host=${server_url#https://}
case "$trusted_host" in */*|*:*|*@*) fail "Use only the HTTPS origin, without a path, port, or account name." ;; esac

printf '\nUse the recommended SQLite database? [Y/n] '
IFS= read -r database_choice
case "$database_choice" in
  n|N|no|NO) database_mode=postgres ;;
  *) database_mode=sqlite ;;
esac

command -v openssl >/dev/null 2>&1 || fail "OpenSSL is required to generate private setup secrets."
command -v curl >/dev/null 2>&1 || fail "curl is required to verify the private server address."
application_secret=$(openssl rand -hex 64)
bootstrap_token=$(openssl rand -hex 24)
postgres_password=$(openssl rand -hex 32)

umask 077
{
  printf '%s\n' "WATCHTRACKER_ACCESS_MODE=server"
  printf '%s\n' "WATCHTRACKER_PUBLIC_BASE_URL=$server_url"
  printf '%s\n' "WATCHTRACKER_APPLICATION_SECRET=$application_secret"
  printf '%s\n' "WATCHTRACKER_SERVER_BOOTSTRAP_TOKEN=$bootstrap_token"
  printf '%s\n' "WATCHTRACKER_TRUSTED_HOSTS=$trusted_host"
  printf '%s\n' "WATCHTRACKER_TRUSTED_PROXY_IPS=172.30.0.1,127.0.0.1,::1"
  printf '%s\n' "WATCHTRACKER_SERVER_BACKUP_INTERVAL_HOURS=24"
  printf '%s\n' "WATCHTRACKER_SERVER_BACKUP_RETENTION=14"
  if [ "$database_mode" = postgres ]; then
    printf '%s\n' "POSTGRES_USER=pmt"
    printf '%s\n' "POSTGRES_DB=pmt"
    printf '%s\n' "POSTGRES_PASSWORD=$postgres_password"
    printf '%s\n' "WATCHTRACKER_DATABASE_URL_OVERRIDE=postgresql+psycopg://pmt:$postgres_password@database:5432/pmt"
  fi
} > server.env
chmod 600 server.env

if [ "$database_mode" = postgres ]; then
  compose -f compose.yaml -f compose.postgres.yaml pull
  compose -f compose.yaml -f compose.postgres.yaml up -d --wait --wait-timeout 180
else
  compose -f compose.yaml pull
  compose -f compose.yaml up -d --wait --wait-timeout 180
fi

if [ -n "$tailscale_bin" ]; then
  say "Preparing the private HTTPS address. Follow any Tailscale consent link shown below."
  "$tailscale_bin" serve --bg 8000
fi

wait_for_private_https "$server_url" || fail "PMT started locally, but its private HTTPS address did not answer. Keep PMT and Tailscale running, then use scripts/pmt-server-control.sh status and logs."

say "PMT Server Beta is installed."
printf '%s\n' "Private connection verified. Keep this host and Tailscale running while other devices use PMT."
printf '%s\n' "Open: $server_url"
printf '%s\n' "One-time setup code: $bootstrap_token"
if command -v open >/dev/null 2>&1; then
  open "$server_url" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$server_url" >/dev/null 2>&1 || true
fi
printf '%s\n' "Create the server account in the page that opens."
printf '%s\n' "Then run: scripts/pmt-server-control.sh finish-setup"
printf '%s\n' "Later controls: scripts/pmt-server-control.sh status|start|stop|backup|logs"
