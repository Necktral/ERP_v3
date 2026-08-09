# Auditoría forense integral — ERP_v3 (2026-08)

## Identidad de la corrida

- Rama local: `audit/forense-integral-2026-08`
- Base: `f447f0def5717357a0de68f252d9821c731dbf0d`
- Datos: exclusivamente PostgreSQL/servicios QA aislados; la DB del demo queda fuera de alcance.
- Regla: bug documentado antes del fix; prueba de regresión obligatoria; commits locales; sin push.

## Baseline inicial

- 7 kernels, 35 módulos, 504 rutas backend, 181 migraciones y 662 archivos de prueba backend.
- Sólo 4 archivos Vitest; no existe suite E2E de navegador.
- Las evidencias históricas no certifican el HEAD actual: los ejecutables frontend locales estaban vacíos y producían falsos verdes.
- Estado inicial confirmado: BUG-021..030 y BUG-034 abiertos en `BUGS.md`.
- Supply chain frontend actualizada: auditorías de producción y Capacitor sin vulnerabilidades; residual de dos avisos LOW duplicados de `esbuild`, limitado al servidor dev de Windows y pendiente de un salto mayor de app-vite.

## Mejoras registradas

- **MEJ-001 — HECHA:** guard de router por permiso y módulo efectivo; shell nativo limitado a su propósito.
- **MEJ-002 — HECHA:** cambio de empresa/sucursal transaccional con rollback ante fallo de refresh.
- **MEJ-003 — HECHA:** JWT nativos en Keystore/Keychain mediante secure storage, migración de `localStorage`, caché versionada con TTL de 24 h y revalidación al reconectar.
- **MEJ-004 — HECHA:** Quasar en español, fuentes runtime locales y normalización recursiva de envelopes/estados de error.
- **MEJ-005:** límites de uploads/ZIP, filas y celdas; protección de memoria/CPU.
- **MEJ-006:** token biométrico hasheado con rotación y revelación única.
- **MEJ-007 — HECHA:** `compose.prod.yaml` usa imágenes prod, requiere secretos sin defaults, deshabilita override de transporte, no publica DB/backend/dashboard y limita el frontend a loopback; `check --deploy` es bloqueante.
- **MEJ-008 — HECHA:** cada request reporting revalida RBAC y usa la intersección con el techo firmado del token; revocaciones aplican de inmediato y altas posteriores no expanden la capability.
- **MEJ-009:** auditoría de las tablas restantes con datos >200 y paginación donde corresponda.
- **MEJ-010:** query budgets, EXPLAIN e índices sólo con volumen representativo.

## Matriz de ejecución

| Frente | Estado | Evidencia esperada |
|---|---|---|
| Baseline real backend/frontend/guards | EN CURSO | frontend real: lint/typecheck/build PASS, Vitest 37/37 y drift 504/387 PASS; backend completo en ejecución |
| P0 dinero y aislamiento de facturación | HECHO | BUG-022..024, BUG-032 y BUG-034; 42 tests dirigidos verdes |
| P0 tenant/auth/integration/diagnostics | HECHO | BUG-025..030; 189 tests tenant + 24 auth/dashboard verdes |
| Accounting y recuperación cross-kernel | PENDIENTE | CoA, fault injection, reintentos |
| 30 unidades + 5 lentes | PENDIENTE | `AUDITORIA_LOG.md` actualizado |
| Rendimiento/migraciones/rollback | PENDIENTE | budgets, planes y rehearsal |
| Cumplimiento Nicaragua | PENDIENTE | fuentes oficiales + visto bueno humano |
| Regresión y cierre | PENDIENTE | suites/guards/E2E verdes y riesgo residual |

## Protocolo de hallazgos

1. Reproducir sin tocar datos reales.
2. Registrar BUG o MEJ con evidencia.
3. Congelar prueba roja.
4. Aplicar el cambio mínimo compatible.
5. Ejecutar suite dirigida y regresión cross-kernel.
6. Registrar causa, fix, prueba, commit y riesgo residual.
