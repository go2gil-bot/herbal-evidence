#!/usr/bin/env bash
# Show or apply the declared Supabase auth configuration for one environment.
#
#   scripts/auth-config.sh dev diff
#   scripts/auth-config.sh dev push
#   scripts/auth-config.sh production diff
#
# Always run `diff` and read it before `push`. A non-interactive push defaults to
# proceeding, so the diff is the only real review step.
#
# SMTP is per environment, like every other secret here: DEV_SMTP_* and
# PROD_SMTP_*. One shared key would be the only secret crossing the boundary.
# It is included only when all four resolved values are non-empty. With a
# variable missing, the CLI passes "env(SMTP_HOST)" through as a literal string
# and still sets enabled = true, so a half-configured push would enable SMTP with
# nonsense and break sending. Hence: all four, or none.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${1:-}"
ACTION="${2:-diff}"

# Secrets come from the gitignored env file and are never echoed. Sourced first
# so the per-environment selection below can read DEV_* / PROD_* values.
if [ -f "$REPO/supabase/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO/supabase/.env"
  set +a
fi

case "$ENVIRONMENT" in
  dev)
    export SUPABASE_PROJECT_REF=wnttlpxiycghqiibdpjr
    export SITE_URL=https://frontend-dev-62e0.up.railway.app
    export REDIRECT_URL=https://frontend-dev-62e0.up.railway.app/auth.html
    # Local development signs in against the dev project, so its loopback
    # address is allowed here and nowhere else.
    export REDIRECT_URL_ALT=http://localhost:4173/auth.html
    export SMTP_USER="${DEV_SMTP_USER:-${SMTP_USER:-}}"
    export SMTP_PASS="${DEV_SMTP_PASS:-}"
    export SMTP_SENDER="${DEV_SMTP_SENDER:-${SMTP_SENDER:-}}"
    ;;
  production)
    export SUPABASE_PROJECT_REF=sptckumvgpfgluyxxiug
    export SITE_URL=https://frontend-production-ed33.up.railway.app
    export REDIRECT_URL=https://frontend-production-ed33.up.railway.app/auth.html
    # Deliberately the same value: no loopback address in production.
    export REDIRECT_URL_ALT=https://frontend-production-ed33.up.railway.app/auth.html
    export SMTP_USER="${PROD_SMTP_USER:-${SMTP_USER:-}}"
    export SMTP_PASS="${PROD_SMTP_PASS:-}"
    export SMTP_SENDER="${PROD_SMTP_SENDER:-${SMTP_SENDER:-}}"
    ;;
  *)
    echo "usage: $0 <dev|production> [diff|push]" >&2
    exit 2
    ;;
esac

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
mkdir -p "$WORKDIR/supabase"
cp "$REPO/supabase/config.toml" "$WORKDIR/supabase/config.toml"

if [ -n "${SMTP_HOST:-}" ] && [ -n "${SMTP_USER:-}" ] && [ -n "${SMTP_PASS:-}" ] && [ -n "${SMTP_SENDER:-}" ]; then
  cat "$REPO/supabase/config.smtp.toml" >> "$WORKDIR/supabase/config.toml"
  echo "SMTP: all four variables present, including the smtp block" >&2
else
  echo "SMTP: not configured, leaving the remote sender untouched" >&2
fi

case "$ACTION" in
  diff) npx --yes supabase@latest config diff --workdir "$WORKDIR" --project-ref "$SUPABASE_PROJECT_REF" ;;
  push) npx --yes supabase@latest config push --workdir "$WORKDIR" --project-ref "$SUPABASE_PROJECT_REF" --yes ;;
  *) echo "action must be diff or push" >&2; exit 2 ;;
esac
