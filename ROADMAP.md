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
- O2-O7: pendientes (el detalle de cada oleada vive en el plan de trabajo; los huérfanos por cerrar
  están enumerados con su oleada en `qa/contracts/api_frontend_drift_baseline.json`).
