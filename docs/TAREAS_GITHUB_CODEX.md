# Tareas de GitHub — para ejecutar por CODEX

> **Regla de trabajo:** Claude NO ejecuta operaciones de GitHub (push, PRs, merges,
> rulesets, Actions). Todo lo que toque GitHub se documenta AQUÍ y lo realiza Codex.
> Claude mantiene este doc actualizado al cierre de cada oleada.

## Contexto

Programa de oleadas de rendimiento/cableado de los 7 kernels (ver `ROADMAP.md`
§"Programa de oleadas"). Cada oleada vive en su rama, **apilada** sobre la anterior
(O1 nace de O0, O2 de O1, …) porque cada una usa la infraestructura de la previa.
El repo aún NO se ha subido a GitHub: el push está **bloqueado hasta que el repo sea
privado** (pendiente global del ROADMAP).

## Estado de ramas locales (actualizar al cierre de cada oleada)

| Rama | Commit | Estado | Contenido |
|------|--------|--------|-----------|
| `main` | `5c3a205` | base | Baseline v3 + paso 1 validado + auditoría U1/U8/U12 parcial |
| `oleada-0/infra-transversal` | `7fe535e` | lista para PR | Memo RBAC por-request, CACHES, red assertNumQueries, paginación server-side (useListadoServer + pilotos), guard L4 (`qa/api_frontend_drift_guard.py`), fix 403 background (BUG-006) |
| `oleada-1/venta-fact-inv` | `ae1d5ec` | lista para PR | bulk_create líneas venta/pedido + golden tests, filtro sargable, remisiones/conteo sin N+1, U8 HECHO (BUG-007), UI pedido-con-crédito SoD, Existencias/Kardex server-side |
| `oleada-2/venta-pay-acct` | `efeed07` | lista para PR | post_journal_drafts optimizado, GL totales en BD + tope, suggest_matches batch, U10/U11 HECHAS (BUG-008, BUG-009), UI reconciliación operativa + summary consolidación, tablas intents/intercompany server-side |
| `oleada-3/nomina-perf` | `e2d874b` | lista para PR | planilla con bulk_update atómico + golden de equivalencia, tramos IR cacheados (N+1 real), dedupe biométrico por lote, tablas entries/marcas server-side (PR-4, después de PR-3) |
| `oleada-4/asistencia-campo` | `03d9e75` | lista para PR | UI completa del flujo field/* (5 páginas, 15 huérfanos L4 cerrados), U15 HECHO con tests de idempotencia (PR-5, después de PR-4) |
| `oleada-5/portfolio` | `bbf604e` | lista para PR | cartera sargable en BD, doble-CxC blindado (advisory lock bigint), U12 HECHO, UI intereses/settings + fixes de permiso fantasma y tipo Credit (PR-6) |
| `oleada-6/reporting` | `944c8df` | lista para PR | adaptadores hr/inventory en BD, cache CACHE_ALLOWED TTL 45s, módulo frontend de reportes completo (7 huérfanos cerrados) (PR-7) |
| `oleada-7/sync-y-cierre` | _(último commit de la rama)_ | lista para PR | riel POS con chunking + savepoints, diccionario de códigos L4b, barrido final de tablas (26 server-side), guard L4 BLOQUEANTE en CI (PR-8, cierra el programa) |

## Tareas para Codex (en orden)

1. **Precondición:** crear/verificar el repo GitHub **privado** para ERP_v3.
   No subir nada mientras el repo sea público (regla del ROADMAP).
2. **Push inicial:** `main` primero; luego las ramas de oleada EN ORDEN
   (`oleada-0/...` → `oleada-1/...` → `oleada-2/...`). Sin force-push.
3. **PRs apilados, uno por oleada, merge EN ORDEN:**
   - PR-1: `oleada-0/infra-transversal` → `main`. Título: `feat(oleada-0): infra
     transversal de rendimiento y cableado de kernels`. El cuerpo sale del mensaje
     del commit `7fe535e` (es autodescriptivo).
   - PR-2: `oleada-1/venta-fact-inv` → `main` (mergear DESPUÉS de PR-1; el diff se
     reduce solo a lo de O1 una vez mergeado O0).
   - PR-3: `oleada-2/venta-pay-acct` → `main` (después de PR-2).
   - Merge con **merge commit** (no squash): los mensajes de commit por oleada son
     el registro del programa.
4. **Checks previos a cada merge** (correr en local o CI; todos deben estar verdes):
   - Suite backend canónica: `docker compose exec -T backend bash -lc "cd /app/backend && export DJANGO_SETTINGS_MODULE=config.settings.test; pytest -q"`
   - Guards: `python3 qa/route_authz_guard.py --root . --baseline qa/contracts/route_authz_baseline.json --output qa/reports/route_authz_guard.json`,
     `python3 qa/api_frontend_drift_guard.py`, y `qa-route-contract-guard` (en docker).
   - Frontend: `npm run typecheck && npm run lint` y `node ./node_modules/vitest/vitest.mjs run` en `frontend/`.
5. **CI de GitHub:** si se activan los workflows existentes, verificar que el paso
   report-only del guard L4 (`qa/run_qa_ci.sh`, línea `api_frontend_drift_guard.py
   --report-only`) corre; queda pendiente volverlo bloqueante (quitar `--report-only`)
   una vez mergeadas O0+O1 — hacerlo en un commit propio.
6. **Después de cada merge:** actualizar la tabla de arriba (estado → "mergeada",
   PR #) y borrar las ramas remotas ya mergeadas si el flujo del repo lo permite.

## Notas

- Los targets `qa-github-required-checks-guard`, `qa-github-master-ruleset-verify` y
  `qa-github-master-ruleset-apply` del Makefile existen para gobernanza de GitHub:
  correrlos/configurarlos es tarea de Codex cuando el repo remoto exista.
- Las oleadas futuras (O3-O7) añadirán filas a la tabla; mismo flujo de PR apilado.
