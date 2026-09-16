#!/bin/sh
# Write the public runtime config from environment variables, then serve.
# Only PUBLIC values are written here. A secret must never reach this file.
set -eu

cat > /srv/config.js <<CONFIG
window.APP_CONFIG = {
  APP_ENV: "${APP_ENV:-dev}",
  API_BASE_URL: "${API_BASE_URL:-}",
  SUPABASE_URL: "${SUPABASE_URL:-}",
  SUPABASE_PUBLISHABLE_KEY: "${SUPABASE_PUBLISHABLE_KEY:-}"
};
CONFIG

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
