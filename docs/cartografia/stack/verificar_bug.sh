#!/usr/bin/env bash
# verificar_bug.sh — verificación de un commit F del port (rojo→verde) en el stack erpv3_pr9.
#
# Corre las pruebas dirigidas y cruzadas que se le pasen, más las guardias de tipado, permisos,
# contratos de rutas, cableado frontend↔API y arquitectura. Deja todo en una corrida nueva de
# .evidencia (JUnit, logs, reportes de guardias) y una línea por paso en steps.tsv.
#
# Uso: verificar_bug.sh <etiqueta> <rutas de pytest relativas a backend/> [-- <make targets extra>]
set -uo pipefail

STACK_DIR=/home/wis/dev/ERP_v3_forensic/docs/cartografia/stack
E="$STACK_DIR/erpbl"
EV=/home/wis/dev/ERP_v3_forensic/.evidencia
export ERPBL_TREE=pr9
ROOT=/home/wis/dev/ERP_v3_pr9

TAG="${1:?uso: verificar_bug.sh <etiqueta> <rutas pytest> [-- <targets extra>]}"; shift
PATHS=(); EXTRA=()
while (($#)); do
  if [[ "$1" == "--" ]]; then shift; EXTRA=("$@"); break; fi
  PATHS+=("$1"); shift
done

RUN="$("$E" run-start "verde-$TAG")" || exit 1
REL="${RUN#$EV/}"
STEPS="$RUN/steps.tsv"
step() {
  local name="$1"; shift
  local t0 rc
  t0="$(date +%s)"
  "$@" >"$RUN/logs/$name.log" 2>&1
  rc=$?
  printf '%s\t%s\t%s\n' "$name" "$rc" "$(( $(date +%s) - t0 ))" >> "$STEPS"
  echo "$name rc=$rc"
}

# Los reportes de guardias se escriben en qa/reports/final del árbol pr9: se crea como el
# usuario del host para poder moverlo después (si lo crea el contenedor, queda de root).
mkdir -p "$ROOT/qa/reports/final"

step pytest "$E" exec-backend "cd /app/backend && DJANGO_SETTINGS_MODULE=config.settings.test PYTEST_DB_SLOT=pr9 pytest ${PATHS[*]} -p no:cacheprovider -q --junitxml=/evidencia/$REL/reports/junit_verde.xml"
for t in qa-backend-mypy qa-route-authz-guard qa-route-contract-guard qa-l4-drift qa-architecture-dependency-guard "${EXTRA[@]}"; do
  step "$t" "$E" make "$t"
done

mv "$ROOT/qa/reports/final" "$RUN/reports/guardias"
echo "evidencia: $RUN"
