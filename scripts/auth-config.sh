#!/usr/bin/env bash
# Show or apply the declared Supabase auth configuration for one environment.
#
#   scripts/auth-config.sh dev diff
#   scripts/auth-config.sh dev push
#   scripts/auth-config.sh production diff
#
# Always run `diff` and read it before `push`. A non-interactive push defaults
# to proceeding, so the diff is the only real review step.
set -euo pipefail

ENVIRONMENT="${1:-}"
ACTION="${2:-diff}"

case "$ENVIRONMENT" in
  dev)
    export SUPABASE_PROJECT_REF=wnttlpxiycghqiibdpjr
    export SITE_URL=https://frontend-dev-62e0.up.railway.app
    export REDIRECT_URL=https://frontend-dev-62e0.up.railway.app/auth.html
    # Local development signs in against the dev project, so its loopback
    # address is allowed here and nowhere else.
    export REDIRECT_URL_ALT=http://localhost:4173/auth.html
    ;;
  production)
    export SUPABASE_PROJECT_REF=sptckumvgpfgluyxxiug
    export SITE_URL=https://frontend-production-ed33.up.railway.app
    export REDIRECT_URL=https://frontend-production-ed33.up.railway.app/auth.html
    # Deliberately the same value: no loopback address in production.
    export REDIRECT_URL_ALT=https://frontend-production-ed33.up.railway.app/auth.html
    ;;
  *)
    echo "usage: $0 <dev|production> [diff|push]" >&2
    exit 2
    ;;
esac

case "$ACTION" in
  diff) npx --yes supabase@latest config diff --project-ref "$SUPABASE_PROJECT_REF" ;;
  push) npx --yes supabase@latest config push --project-ref "$SUPABASE_PROJECT_REF" --yes ;;
  *) echo "action must be diff or push" >&2; exit 2 ;;
esac
