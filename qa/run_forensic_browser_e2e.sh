#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -p erpv3_forensic -f "$ROOT_DIR/compose.forensic.yaml" -f "$ROOT_DIR/compose.forensic.browser.yaml")
: "${FORENSIC_E2E_PASSWORD:?FORENSIC_E2E_PASSWORD is required}"

"${COMPOSE[@]}" up -d db backend frontend
if ! "${COMPOSE[@]}" exec -T backend python manage.py seed_dev_environment \
  --allow-non-debug --reset-password --admin-username forensic_admin \
  --admin-password "$FORENSIC_E2E_PASSWORD" --holding-name 'Holding Forense' \
  --company-name 'Empresa Forense' --branch-name 'Sucursal Forense' >/dev/null 2>&1; then
  echo "forensic admin seed failed (output suppressed to protect credentials)" >&2
  exit 1
fi
"${COMPOSE[@]}" exec -T backend python manage.py shell -c \
  "from apps.modulos.iam.models import OrgUnit; OrgUnit.objects.filter(name='Empresa Forense').update(code='FORENSIC-CO'); OrgUnit.objects.filter(name='Sucursal Forense').update(code='FORENSIC-BR')"
"${COMPOSE[@]}" exec -T -e FORENSIC_BROWSER_SEED=1 -e FORENSIC_E2E_PASSWORD backend python manage.py shell < "$ROOT_DIR/qa/browser/seed_forensic_browser.py"

for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:${FORENSIC_FRONTEND_PORT:-13000}/ >/dev/null && break
  sleep 1
done

cd "$ROOT_DIR/frontend"
npx playwright install chromium
E2E_BASE_URL="http://127.0.0.1:${FORENSIC_FRONTEND_PORT:-13000}" \
  FORENSIC_E2E_PASSWORD="$FORENSIC_E2E_PASSWORD" npx playwright test
