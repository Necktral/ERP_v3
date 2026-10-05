# ROADMAP — ERP_v3

Estado de construcción, paso por paso. Manda el orden del `CLAUDE.md` / `ARQUITECTURA_V3.md`.

> **Regla:** no se avanza al siguiente paso hasta que el actual **pase la prueba del usuario del campo** y tenga sus bugs arreglados (ver `BUGS.md`).

## Estados

- **TODO** — no empezado
- **DOING** — en construcción / prueba
- **DONE** — pasó todos los criterios de abajo y cerró limpio
- **BLOCKED** — trabado por una dependencia o un bug abierto (anotar cuál en Notas)

## Criterios para marcar DONE (los 7, todos)

- [ ] Un usuario del campo lo completa **sin que nadie le explique**
- [ ] Flujo lineal: paso 1 → 2 → 3 → listo
- [ ] Mensajes claros en español (nada de códigos de error crudos)
- [ ] Validaciones que **guían** (dicen qué falta), no rechazan en seco
- [ ] Cierra **limpio en contabilidad** (sin descuadres)
- [ ] No genera inconsistencias con módulos ya probados
- [ ] Anda bien en tablet / móvil

## Alcance del demo

**UNA sola empresa.** Módulos encendidos: contabilidad, HR, nómina, inventario, compras, ventas/POS, payments, portfolio.
El resto (fleet, beneficio, estación de servicios, financiamiento, etc.) queda **apagado — no se borra, no se enciende.**

## Pasos de construcción

| #  | Paso                                                        | Estado | Notas |
|----|-------------------------------------------------------------|--------|-------|
| 1  | Estructura organizacional (holding → empresa → sucursal)    | DONE   | Verificado E2E por la UI real · BUG-001 cerrado · ver bitácora ↓ |
| 2  | Contabilidad base (CoA, período fiscal, tipo de cambio)     | DOING  | En prueba manual por UI (guión B2–B4) · el período fiscal se abre solo al primer posteo (ver bitácora) |
| 3  | HR + asistencia (empleados y fichaje)                       | TODO   |       |
| 4  | Nómina (se apoya en HR + contabilidad)                      | TODO   |       |
| 5  | Inventarios                                                 | TODO   |       |
| 6  | Compras / CxP (proveedores, entrada de mercadería)          | TODO   |       |
| 7  | Ventas / POS / CxC (clientes, caja, crédito)                | TODO   |       |
| 8  | Caja / arqueo (apertura y cierre que cuadran)               | TODO   |       |
| 9  | Payments (cierra cobros y pagos)                            | TODO   |       |
| 10 | Portfolio + reportes (cartera viva y visibilidad)           | TODO   |       |

*Al empezar un paso, pasarlo a DOING; al cerrar limpio, a DONE.*

---

## Bitácora

### Paso 1 — Estructura organizacional · DONE (2026-07-01)

- **Entorno v3 levantado con DB vacía** (docker: `db + backend + frontend`). El copiado de v3 estaba incompleto: se trajo `requirements/` de v2 y se creó el `.env` de raíz. `dash_analytics` no se levanta (no hace falta).
- **Empresa creada a mano por el wizard real** (no seed): Holding **Agrícola Santa Isabel** → Empresa **Comisariato Santa Isabel** (RUC J0310000012345) → Sucursal **Casa Matriz**. Moneda **NIO (C$)** confirmada en el tablero.
- **BUG-001 encontrado y cerrado**: el admin rebotaba a `/login` tras el wizard (estado `is_fresh` cacheado). Fix en `frontend/src/stores/auth.store.ts`. Re-verificado E2E: ahora entra directo al tablero.
- **BUG-002 abierto** (media): el admin del bootstrap es superusuario permanente, no "temporal que se desactiva" — a resolver en el paso 3 (HR/empleado-administrador).
- **Los 7 criterios del usuario del campo: verificados** (flujo lineal, español claro, validaciones que guían, cierra limpio, sin inconsistencias, responsive tablet/móvil).
- **Módulos:** los verticales (fleet, beneficio, financiamiento, fuel, cec, comisariato, finca) quedan OFF por default — la regla "el resto apagado" se cumple sola.

**Pendiente global (no bloquea):** push de la baseline a GitHub, bloqueado hasta que el repo v3 sea **privado**.

---

### Paso 2 — Contabilidad base · DOING (preflight 2026-08-08)

- **B1 aprobado:** `Contador → Contabilidad` está cableado a `/contabilidad`; desde el panel se accede a `/contabilidad/plan-cuentas`, `/contabilidad/monedas` y `/contabilidad/periodos`.
- **Módulo y permisos:** `accounting` está habilitado como módulo core. El usuario `admin` del demo es superusuario y puede leer/editar CoA, registrar FX y leer períodos.
- **Entorno:** frontend y health de accounting responden HTTP 200. Estado inicial de la empresa **Comisariato Santa Isabel**: 0 cuentas, 0 tasas y 0 períodos.
- **B2–B4:** guión manual entregado a Wis; monitor de DB activo durante la prueba. Pendiente registrar observaciones de UX y verificar por API/DB los datos creados.

---

## Auditoría profunda (escaneo de bugs) — documentada, pendiente de ejecutar

Se **diseñó** una auditoría profunda de todo el repo (30 unidades + 5 lentes transversales, con
hot-spots a nivel archivo:línea) y se **preparó el arnés** (Fase 0: `qa/` repuesto, suite backend
verde, BUG-003 cerrado). La **ejecución** (Fase 1 revisión → Fase 2 fixes crítico/alto → Fase 3
regresión) quedó **pendiente**: la flota multi-agente topó el límite de sesión.

Todo está documentado como runbook auto-contenido para ejecutarlo en frío:
**[`docs/ESCANEO_PROFUNDO_OPUS.md`](docs/ESCANEO_PROFUNDO_OPUS.md)** — catálogo de unidades/lentes,
comandos del arnés, protocolo de hallazgos (BUGS.md primero), restricciones, y hallazgos preliminares
ya verificados a mano. Recomendación: correr en lotes chicos / inline para no repetir el tope de cuota.

---

## Programa de oleadas — rendimiento de kernels + cableado (2026-07-02, en curso)

Programa en 8 oleadas para mejorar **perf de ejecución + cableado backend↔frontend + robustez** de
los 7 kernels. Una rama mergeable por oleada; cache **in-process** (sin Redis/Celery); los huecos de
cableado se cierran TODOS en su oleada. Secuencia: **O0** infra transversal → **O1** facturación+
inventarios → **O2** payments+accounting → **O3** nómina núcleo → **O4** nómina field/* (UI) →
**O5** portfolio → **O6** reporting → **O7** sync_engine + cierre frontend.

- **O0 — infra transversal (`oleada-0/infra-transversal`): HECHA.** Memo RBAC por-request (la 2ª
  evaluación de permisos del mismo request = 0 queries, con tests); `CACHES` explícito (default +
  alias `catalogs` TTL 300); red de budgets de queries (`backend/src/tests/perf/`, ratchet);
  paginación server-side (`useListadoServer` + pilotos FacturacionPage/DiarioPage); fix del
  interceptor 403 para requests background (BUG-006); guard L4 `qa/api_frontend_drift_guard.py`
  (0 cableado roto, 43 huérfanos kernel baselineados con razón/oleada) — `make qa-l4-drift`,
  report-only en CI (bloqueante desde O1). Unidades tocadas: U3, U22, L4 (EN-CURSO en
  `docs/AUDITORIA_LOG.md`).
- **O1 — facturación + inventarios (`oleada-1/venta-fact-inv`): HECHA.** Golden tests de líneas
  byte-a-byte ANTES del refactor; `bulk_create` de líneas (doc y pedido); filtro de fechas sargable;
  remisiones sin N+1 (ítems en 1 query + bulk); conteo físico con `bulk_update` y balances agrupados;
  budgets O(1)-en-líneas (create_draft / create_remision). **U8 HECHO** (6 tests: idempotencia
  warehouse/qty/lote + transferencias cruzadas concurrentes sin deadlock) con **BUG-007** (la
  idempotencia no comparaba el lote) encontrado por test y cerrado. UI pedido-con-crédito SoD
  completa (PedidosPage + AprobacionesCreditoPage + `pending_approval_id` en el payload del pedido);
  Existencias y Kardex con paginación server-side. Baseline L4: 43 → 40 huérfanos.
- **O2 — payments + accounting (`oleada-2/venta-pay-acct`): HECHA.** `post_journal_drafts` sin
  N+1 (select_related + `of=("self",)` + config cacheada por run; el check de período CLOSED se lee
  fresco por draft a propósito); GL del reporting con totales agregados en BD + tope 5000 filas con
  warning; `suggest_matches` de conciliación batcheado (1 query global, misma semántica);
  denominaciones de arqueo con bulk_create (subtotal explícito — save() no corre en bulk).
  **U10 y U11 HECHAS** con **BUG-008** (apertura de caja concurrente → 500 crudo en vez de 409 de
  dominio) encontrado por test y cerrado; cierre de caja y match de intent concurrentes certificados.
  Índice GL **diferido con razón** (BD dev sin datos: EXPLAIN no valida; retomar con volumen).
  UI: ReconciliacionOperativaPage + resumen de consolidación por corrida; tablas de intents e
  intercompany a paginación server-side. Baseline L4: 40 → 39 huérfanos.
- **O3 — nómina núcleo (`oleada-3/nomina-perf`): HECHA.** `compute_all_entries_in_sheet` con UN
  bulk_update atómico (antes: un UPDATE completo por entrada; `updated_at` fijado explícito) —
  equivalencia garantizada por golden campo-por-campo masivo==individual + punto fijo; tramos IR
  cacheados por instancia de config (antes: 1 query de tramos POR entrada — N+1 real no previsto en
  el plan); ingesta biométrica con dedupe por lote (1 query de keys + bulk_create). Budget: recalcular
  planilla de 3 y de 12 entradas cuesta las MISMAS queries. U13/U14 EN-CURSO. UI: entradas de
  planilla y marcas biométricas con paginación server-side (las no migradas quedaron documentadas
  con razón: pay-summary no pagina y es offline-first; asistencia/hoy acotada al día).
- **O4 — asistencia de campo (`oleada-4/asistencia-campo`): HECHA.** UI completa del flujo field/*
  — el hueco de cableado más grande: JornadasCampoPage, JornadaDetallePage (pase de lista, cuadrillas,
  eventos, traslados, consolidación), AprobacionesCampoPage (checker SoD + aplicar a planilla),
  ReporteCuadrillaPage y CapturaCampoPage (flujo lineal PR#17, móvil-first). 15 huérfanos L4 cerrados
  (baseline 39 → 24). **U15 HECHO**: SoD certificado + 2 tests nuevos de idempotencia (re-consolidar
  no duplica y se bloquea tras aprobar; re-aplicar no mueve días ni neto). MEJORA anotada: faltan GET
  de solicitudes SoD y de cuadrillas/rollcall del día (la UI degrada a bitácora/localStorage).
- **O5 — portfolio (`oleada-5/portfolio`): HECHA.** Cartera vencida filtrada sargable en la BD
  (outstanding con F() — antes cargaba TODA la cartera a Python) y último recordatorio por grupo en
  1 query (DISTINCT ON); budget: la mesa de cobranza cuesta lo mismo con 2 que con 8 clientes.
  **U12 HECHO**: doble-CxC concurrente verificado (test 2 hilos) + endurecido con advisory lock
  bigint (hashtextextended — la forma de 2 args es int4 y desbordaría con BigAutoField). UI:
  InteresesPage (devengos con detalle), ConfiguracionCarteraPage (settings honestos: solo lo
  implementado), detalle de crédito con devengos; fixes de la revisión: permiso fantasma
  `portfolio.payment.allocation.read` (la pestaña Aplicaciones nunca se mostraba) y tipo `Credit`
  desalineado del serializer. Baseline L4: 24 → 19 (retrieves sin campos extra baselineados con
  razón honesta, no cableado postizo).
- **O6 — reporting (`oleada-6/reporting`): HECHA.** Adaptadores hr (headcount con GROUP BY en BD) e
  inventory (totales agregados en BD + detalle con tope 5000 y warning — patrón GL) — antes iteraban
  todo en Python; cache TTL 45s SOLO para datasets `CACHE_ALLOWED` (contrato de freshness; LIVE_ONLY
  nunca cachea) con copias profundas. fuel.py DIFERIDO con razón (módulo dormido todo el demo).
  UI: módulo `reportes` nuevo — CatalogoReportesPage (ejecutar con filtros dinámicos por
  filters_schema, exportar con POLL en background y backoff, vistas guardadas), EjecucionesPage y
  SnapshotsPage (server-side); las funciones reporting salen del dashboard a una sola casa.
  Baseline L4: 19 → 12 huérfanos. U21 EN-CURSO.
- **O7 — sync + cierre de calidad frontend (`oleada-7/sync-y-cierre`): HECHA.** Riel POS offline:
  `process_batch` con UNA transacción por chunk de 20 comandos + savepoint explícito por comando
  (antes: un commit/fsync por comando; misma semántica de fallo y respuesta, 100 tests sync/POS
  verdes). Frontend: poll del tablero con skip-si-no-cambió; diccionario central de códigos
  (`core/codigos.ts` — L4b cerrada: los códigos crudos del backend se traducen a español); barrido
  final de tablas (26 páginas en server-side; las restantes con comentario de decisión explícita;
  las de módulos dormidos intactas). Guard L4 ahora **BLOQUEANTE en CI**. U19 EN-CURSO (kill-switch
  y firma quedan para certificación futura), U22 HECHO.

**PROGRAMA DE OLEADAS COMPLETO (O0-O7).** Resultado global: baseline L4 de 43 → 12 huérfanos
justificados y 0 cableado roto; red de budgets de queries (ratchet) en `src/tests/perf/`; 4 bugs
encontrados por test y cerrados (BUG-006 a BUG-009) + 2 endurecimientos de concurrencia (advisory
locks); U8/U10/U11/U12/U15/U22/L4 HECHAS y U5/U7/U9/U13/U14/U19/U21/U26 avanzadas. Las ramas de
oleada esperan PR en orden (ver `docs/TAREAS_GITHUB_CODEX.md`).
