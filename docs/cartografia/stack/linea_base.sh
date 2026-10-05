#!/usr/bin/env bash
# linea_base.sh — corre la línea base completa del árbol indicado, PASO POR PASO y sin cortar.
#
# Requisitos: stack aislado arriba (erpbl compose up -d db backend) y corrida iniciada
# (erpbl run-start <tipo>). Todo docker/make pasa por erpbl. Cada paso deja su log en
# <corrida>/logs/<paso>.log y una línea "paso<TAB>rc<TAB>segundos" en <corrida>/steps.tsv.
#
# Uso: ERPBL_TREE=forensic|pr9 linea_base.sh [--sin-e2e]
set -uo pipefail

STACK_DIR=/home/wis/dev/ERP_v3_forensic/docs/cartografia/stack
E="$STACK_DIR/erpbl"
RUN="$("$E" run-dir)" || exit 1
ROOT="$(sed -n 's/^arbol=//p' "$RUN/corrida.env")"
case "${ERPBL_TREE:-forensic}" in pr9) FRONTEND_PORT=13001 ;; *) FRONTEND_PORT=13000 ;; esac
SIN_E2E=0; [[ "${1:-}" == "--sin-e2e" ]] && SIN_E2E=1
STEPS="$RUN/steps.tsv"
FINAL="$ROOT/qa/reports/final"
cd "$ROOT" || exit 1

step() {
  local name="$1"; shift
  local t0 rc
  t0="$(date +%s)"
  echo "[$(date -u +%H:%M:%SZ)] >> $name"
  "$@" >"$RUN/logs/$name.log" 2>&1
  rc=$?
  printf '%s\t%s\t%s\n' "$name" "$rc" "$(( $(date +%s) - t0 ))" >> "$STEPS"
  echo "[$(date -u +%H:%M:%SZ)] << $name rc=$rc"
  return 0
}

# --- 0. Corrida canónica (run_qa_ci.sh tal cual) ---
step 00-canonico "$E" qa-ci
mkdir -p "$RUN/canonico" && cp -a "$FINAL/." "$RUN/canonico/" 2>/dev/null

# --- 1. Gate 1, paso por paso ---
GATE1=(qa-namespace-guard qa-analytics-contract-guard qa-route-contract-guard qa-l4-drift qa-readme-section-guard
  qa-pr-blast-radius-guard qa-reporting-registry-guard qa-reporting-contract-version-guard qa-pythonpath-bootstrap-guard
  qa-backend-package-check qa-architecture-dependency-guard qa-action-pin-guard qa-github-required-checks-guard
  qa-runner-hygiene-guard qa-validate-security-exceptions qa-security-audits qa-security-findings-enforce
  qa-static-scan qa-backend-bandit qa-backend-ruff qa-backend-mypy qa-verify-static-gate qa-makemigrations-check
  qa-migration-safety-guard qa-frontend-ci)
i=10; for t in "${GATE1[@]}"; do step "g1-$((i++))-$t" "$E" make "$t"; done

# --- 2. Gate 2 ---
GATE2=(qa-backend-tests qa-sync-contract-guard qa-retail-pos-backend-contract-guard qa-retail-pos-sync-contract-guard
  qa-retail-pos-frontend-queue-contract-guard qa-retail-pos-edge-simulator-guard qa-retail-pos-edge-e2e-guard
  qa-coverage-by-domain-guard)
i=40; for t in "${GATE2[@]}"; do step "g2-$((i++))-$t" "$E" make "$t"; done

# --- 3. Gate 3 ---
GATE3=(qa-audit-integrity qa-reporting-r8-gate qa-verify-reporting-r8-gate-artifact qa-export-u6-release-evidence)
i=60; for t in "${GATE3[@]}"; do step "g3-$((i++))-$t" "$E" make "$t"; done

# --- 4. Extras que el runner no corre ---
step x-70-route-authz "$E" make qa-route-authz-guard
step x-71-governance "$E" make qa-codex-governance-guard
step x-72-migration-rehearsal "$E" make qa-migration-rehearsal
step x-73-openapi "$E" exec-backend "cd /app && python qa/openapi_contract_guard.py --root /app --output qa/reports/final/openapi_contract_guard.json"
step x-74-preflight-prod "$E" exec-backend 'cd /app/backend && export DJANGO_SETTINGS_MODULE=config.settings.prod \
  DJANGO_SECRET_KEY="$(python -c "import secrets;print(secrets.token_urlsafe(64))")" \
  AUDIT_HMAC_KEY="$(python -c "import secrets;print(secrets.token_urlsafe(48))")"; \
  out=$(python manage.py check --deploy --fail-level ERROR 2>&1); rc=$?; \
  python -c "import json,sys; print(json.dumps({\"status\": \"passed\" if int(sys.argv[1])==0 else \"failed\", \"exit_code\": int(sys.argv[1]), \"command\": \"manage.py check --deploy --fail-level ERROR (settings.prod, claves descartables)\", \"output_tail\": sys.argv[2][-4000:]}, indent=2))" "$rc" "$out" > /app/qa/reports/final/production_preflight.json; exit $rc'
step x-75-pytest-excluidas "$E" exec-backend "cd /app/backend && export DJANGO_SETTINGS_MODULE=config.settings.test PYTEST_DB_SLOT=excluidas && pytest src/apps/modulos/controls/tests src/apps/modulos/documents/tests src/apps/modulos/finca/tests src/apps/modulos/fleet/tests src/apps/modulos/intercompany/tests src/apps/modulos/knowledge/tests src/apps/modulos/notifications/tests --junitxml=/app/qa/reports/final/pytest_excluidas.xml -q"
step x-76-collect-only "$E" exec-backend "cd /app/backend && DJANGO_SETTINGS_MODULE=config.settings.test pytest --collect-only -q | tail -3"

# --- 5. E2E de navegador (seed de banco de trabajo + Playwright en el host) ---
if [[ "$SIN_E2E" == "0" ]]; then
  step e2e-80-seed-admin "$E" compose exec -T -e FORENSIC_E2E_PASSWORD backend bash -lc \
    'python manage.py seed_dev_environment --allow-non-debug --reset-password --admin-username forensic_admin --admin-password "$FORENSIC_E2E_PASSWORD" --holding-name "Holding Forense" --company-name "Empresa Forense" --branch-name "Sucursal Forense" >/dev/null 2>&1 || { echo "seed falló (salida suprimida para no exponer credenciales)"; exit 1; }'
  step e2e-81-seed-codigos "$E" compose exec -T backend python manage.py shell -c \
    "from apps.modulos.iam.models import OrgUnit; OrgUnit.objects.filter(name='Empresa Forense').update(code='FORENSIC-CO'); OrgUnit.objects.filter(name='Sucursal Forense').update(code='FORENSIC-BR')"
  step e2e-82-seed-browser bash -c "'$E' compose exec -T -e FORENSIC_BROWSER_SEED=1 -e FORENSIC_E2E_PASSWORD backend python manage.py shell < '$ROOT/qa/browser/seed_forensic_browser.py'"
  step e2e-83-frontend-up "$E" compose up -d frontend
  step e2e-84-frontend-wait bash -c "for _ in \$(seq 1 300); do curl -fsS http://127.0.0.1:$FRONTEND_PORT/ >/dev/null && exit 0; sleep 2; done; exit 1"
  REV_REQ="$(jq -r '.browsers[] | select(.name=="chromium") | .revision' "$ROOT/frontend/node_modules/playwright-core/browsers.json" 2>/dev/null)"
  if [[ -n "$REV_REQ" && -d "$HOME/.cache/ms-playwright/chromium-$REV_REQ" ]]; then
    step e2e-85-playwright bash -c "cd '$ROOT/frontend' && FORENSIC_E2E_PASSWORD=\"\$(cat /home/wis/dev/ERP_v3_forensic/.evidencia/_stack/secrets/e2e_password)\" \
      E2E_BASE_URL=http://127.0.0.1:$FRONTEND_PORT PLAYWRIGHT_JUNIT_OUTPUT_NAME='$RUN/playwright/junit.xml' \
      ./node_modules/.bin/playwright test --output '$RUN/playwright/test-results' --reporter=line,junit"
  else
    printf 'e2e-85-playwright\t97\t0\n' >> "$STEPS"
    echo "chromium requerido: '${REV_REQ:-?}' no está en caché — E2E bloqueado hasta autorizar la descarga" > "$RUN/logs/e2e-85-playwright.log"
  fi
  step e2e-86-frontend-stop "$E" compose stop frontend
fi

echo "[linea_base] terminado: $RUN"
