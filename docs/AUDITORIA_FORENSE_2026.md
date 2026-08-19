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
- **MEJ-005 — HECHA:** límites antes/durante upload y parseo XLSX/CSV, inspección ZIP, ratio de expansión y presupuestos de filas/celdas.
- **MEJ-006 — HECHA:** token biométrico hasheado, revelación única y rotación; rollout 0020 → código hash-aware → 0021 con rollback legacy fail-safe.
- **MEJ-007 — HECHA:** `compose.prod.yaml` usa imágenes prod, requiere secretos sin defaults, deshabilita override de transporte, no publica DB/backend/dashboard y limita el frontend a loopback; `check --deploy` es bloqueante.
- **MEJ-008 — HECHA:** cada request reporting revalida RBAC y usa la intersección con el techo firmado del token; revocaciones aplican de inmediato y altas posteriores no expanden la capability.
- **MEJ-009 — HECHA:** tablas e historiales conservan envelopes paginados y los selectores de
  Financiamiento, Finca y Fleet usan búsqueda remota acotada; 26 pruebas backend y regresiones
  frontend verifican scope, búsqueda, `limit/offset` y ausencia de recorrido completo.
- **MEJ-010 — HECHA:** BUG-049 congeló un query budget constante del cierre contable: 7 consultas
  tanto para 1 como para 100 drafts, con `EXPLAIN` PostgreSQL documentado.
- **MEJ-011 — HECHA:** `DEMO_PING` sólo se habilita explícitamente en dev/test; producción lo
  rechaza fail-closed y una regresión confirma que los handlers reales siguen registrados.

## Matriz de ejecución

| Frente | Estado | Evidencia esperada |
|---|---|---|
| Baseline real backend/frontend/guards | HECHO | backend 2,071 pruebas, 0 fallos/errores y 1 skip autorizado; frontend lint/typecheck/build, Vitest 58/58 y E2E 4/4 |
| P0 dinero y aislamiento de facturación | HECHO | BUG-022..024, BUG-032 y BUG-034; 42 tests dirigidos verdes |
| P0 tenant/auth/integration/diagnostics | HECHO | BUG-025..030; 189 tests tenant + 24 auth/dashboard verdes |
| Accounting y recuperación cross-kernel | HECHO | CoA, fault injection, reintentos y 115 regresiones dirigidas |
| 30 unidades + 5 lentes | HECHO | `AUDITORIA_LOG.md`: 30/30 unidades y 5/5 lentes |
| Rendimiento/migraciones/rollback | HECHO | guards, plan y aplicación completa desde PostgreSQL vacío; estrategia roll-forward versionada |
| Cumplimiento Nicaragua | HECHO TÉCNICO | reglas y pruebas técnicas cerradas; visto bueno profesional permanece como riesgo humano |
| Regresión y cierre | HECHO | suites, contratos, seguridad, browser E2E y evidencia externa por SHA |

## Protocolo de hallazgos

1. Reproducir sin tocar datos reales.
2. Registrar BUG o MEJ con evidencia.
3. Congelar prueba roja.
4. Aplicar el cambio mínimo compatible.
5. Ejecutar suite dirigida y regresión cross-kernel.
6. Registrar causa, fix, prueba, commit y riesgo residual.

## Incidente de entrega prematura

La auditoría fue entregada anteriormente como finalizada sin satisfacer sus criterios de cierre.
El análisis del incidente determinó:

- Se tomaron mensajes de agentes que decían “completado” para lotes concretos como señal de cierre general.
- No se ejecutó una auditoría final del worktree antes de entregar: quedaron 17 archivos modificados y 11 sin seguimiento.
- Se conservaron reportes fallidos: backend con 2 fallos, gobernanza fallida y OpenAPI fallido.
- `BUG-002`, `BUG-049`, unidades, lentes, E2E y vistos buenos seguían pendientes.
- Faltó un único gate agregador que exigiera worktree limpio, cero bugs abiertos, matrices cerradas y reportes frescos.
- Se añadió ese gate de cierre y una lista de comprobación firmada para impedir otra declaración prematura.

La causa raíz fue confundir cierre de lotes delegados con cierre del objetivo global y no aplicar un
gate final independiente. En adelante, ningún mensaje parcial puede promover el estado a terminado:
el manifest debe corresponder al HEAD, todos los reportes deben ser frescos y `passed`, JUnit debe
estar libre de fallos no permitidos, las 30 unidades y 5 lentes deben estar cerradas, los riesgos
residuales documentados y el worktree limpio. Este documento aún no declara que esos gates finales
hayan sido ejecutados sobre el HEAD integrado.

## Cierre técnico

La campaña cerró BUG-065..069 durante la estabilización final: contaminación global de throttling,
contexto Docker con secretos, Node no soportado en producción, 41 errores Mypy y pantalla POS en
blanco sin `crypto.randomUUID`. La certificación exige y conserva fuera del repositorio el JUnit
backend, reportes frontend/browser, migraciones, seguridad y contratos bajo un directorio nombrado
con el SHA. El SHA autoritativo es el campo `commit` de `run_manifest.json`; no se versionan
evidencias generadas para mantener el worktree limpio.

## Riesgos residuales

- La aprobación fiscal, laboral, contable y legal sigue correspondiendo a profesionales autorizados.
- `pip-audit` reporta vulnerabilidades conocidas cubiertas por excepciones versionadas y frontend
  conserva dos avisos LOW de tooling dev; el ratchet no admite hallazgos nuevos.
- Docker Desktop funciona desde Windows, pero su integración WSL no expone el socket de bind mounts;
  la certificación se ejecutó con contextos e imágenes inmutables sobre el disco Linux.
- No se levantó ni pobló el demo; no hubo push, PR ni despliegue.
