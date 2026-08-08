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

## Mejoras registradas

- **MEJ-001:** guard de router por permiso y módulo efectivo; shell nativo limitado a su propósito.
- **MEJ-002:** cambio de empresa/sucursal transaccional con rollback ante fallo de refresh.
- **MEJ-003:** almacenamiento seguro nativo, TTL offline y revalidación al reconectar.
- **MEJ-004:** Quasar en español, fuentes locales y normalización completa de errores de UI.
- **MEJ-005:** límites de uploads/ZIP, filas y celdas; protección de memoria/CPU.
- **MEJ-006:** token biométrico hasheado con rotación y revelación única.
- **MEJ-007:** compose/perfil productivo fail-closed y sin secretos conocidos por defecto.
- **MEJ-008:** revocación explícita/versionada de capabilities de reporting.
- **MEJ-009:** auditoría de las tablas restantes con datos >200 y paginación donde corresponda.
- **MEJ-010:** query budgets, EXPLAIN e índices sólo con volumen representativo.

## Matriz de ejecución

| Frente | Estado | Evidencia esperada |
|---|---|---|
| Baseline real backend/frontend/guards | EN CURSO | comandos y artefactos fechados |
| P0 dinero y aislamiento de facturación | EN CURSO | BUG-022..024 + tests API/concurrencia |
| P0 tenant/auth/integration/diagnostics | EN CURSO | BUG-025..030 + migraciones/tests |
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
