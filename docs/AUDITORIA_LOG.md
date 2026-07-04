# AUDITORÍA_LOG — ERP_v3 (escaneo profundo)

Registro de progreso y veredictos de la auditoría. **Actualizar después de CADA unidad/lente** (no
al final): es el checkpoint que permite retomar tras un reset de cuota. El runbook completo está en
[`ESCANEO_PROFUNDO_OPUS.md`](ESCANEO_PROFUNDO_OPUS.md).

**Cómo retomar:** la próxima sesión sigue por la primera fila en `PENDIENTE`.

**Leyenda de estado:** `PENDIENTE` · `EN-CURSO` · `HECHO`.
**Veredicto por unidad:** cuántos BUG / MEJORA / VERIFICADO-OK / DECISIÓN salieron, y los IDs.

---

## Progreso — Unidades (30)

| Unidad | Estado | Veredicto (findings / IDs) |
|--------|--------|----------------------------|
| U1 — auth/accounts/2FA/bootstrap | EN-CURSO | **BUG-004** (race bootstrap → 2 superadmins) CERRADO con fix+test. refresh single-flight = VERIFICADO-OK. Falta: 2FA replay, rotación refresh token, flags de cookies, `is_superuser` bypass |
| U2 — iam contexto + middlewares | PENDIENTE | |
| U3 — rbac + org (módulos) | EN-CURSO | Oleada 0: memo RBAC por-request (`get_effective_permissions_for_scope_cached`) elimina las ~3 queries fijas por evaluación repetida; tests en `src/tests/perf/test_query_budgets.py` (2ª evaluación = 0 queries, sin bleed entre requests/companies, override intacto) = VERIFICADO-OK. `route_authz_guard` verde post-cambio. Falta: el resto de la unidad (org, seeds, activación de módulos) |
| U4 — audit + common | PENDIENTE | |
| U5 — accounting: posteo | EN-CURSO | Oleada 2: `post_journal_drafts` optimizado sin cambio de semántica — re-fetch con `select_related` + `select_for_update(of=("self",))` (no bloquea company/branch) + config contable cacheada por run (el check de período CLOSED se lee fresco por draft a propósito); suite accounting completa verde. Falta: certificación profunda de la unidad (SoD approve/post, re-post idempotente bajo concurrencia) |
| U6 — accounting: períodos/FX | PENDIENTE | |
| U7 — accounting: API | EN-CURSO | Oleada 2: GL del adaptador de reporting con totales agregados en la BD (exactos sobre todo el rango) + detalle `values()` con tope 5000 filas y warning de truncamiento (antes: materializaba TODO en Python sin límite). Índice compuesto GL DIFERIDO con razón: la BD dev no tiene datos contables y `explain_financial_queries` no puede validar el plan — retomar cuando haya volumen (paso 2+ del ROADMAP) |
| U8 — inventarios kernel | HECHO | Oleada 1: **BUG-007** (idempotencia no comparaba el LOTE → falso match silencioso) encontrado por test y CERRADO con fix. Idempotency match warehouse/qty/lote = VERIFICADO-OK; `post_transfer` cruzado concurrente sin deadlock (lock ordenado) = VERIFICADO-OK — `tests/test_u8_idempotencia_y_transferencias.py` (6 tests). Costing/reversal/link contable cubiertos por suites existentes verdes (`test_cost_policy`, `test_movement_reversal`, `test_inventory_accounting_integration`). Guard `InsufficientStockError` = VERIFICADO-OK (previo). Bug-hunt integridad: **BUG-014** (transferencia no mezclaba el costo promedio del destino) y **BUG-016** (ajuste/conteo no tocaban `LotBalance` → Σ lotes ≠ saldo) encontrados por test y CERRADOS |
| U9 — facturacion kernel | EN-CURSO | Oleada 1: golden tests de fidelidad de líneas/totales byte-a-byte (`tests/test_golden_lineas_bulk.py`) = VERIFICADO-OK; filtro de fechas sargable; budgets O(1)-en-líneas. Bug-hunt integridad: **BUG-015** (anular factura con efectos dejaba kardex/cartera desalineados → ahora se bloquea y fuerza Nota de Crédito) y **BUG-017** (cobro de borrador/cotización + sin idempotencia → exige ISSUED+INVOICE e idempotency_key) CERRADOS. Falta: void SoD profundo, contingencia fiscal |
| U10 — payments: intents/caja/arqueo | HECHO | Oleada 2: **BUG-008** (apertura de caja concurrente → IntegrityError crudo/500 en vez de 409 de dominio; el constraint único sostenía el invariante) encontrado por test y CERRADO. Cierre de caja concurrente no corrompe arqueo (lock + idempotencia) = VERIFICADO-OK — `tests/test_u10_u11_concurrencia.py`. Intents/estado/SoD/arqueo cubiertos por suites existentes verdes (`test_state_machines`, `test_cash_audit`, `test_payments_sod`, `test_opening_denominations`) |
| U11 — payments: conciliación | HECHO | Oleada 2: match concurrente del MISMO intent contra dos líneas → exactamente uno gana (lock del intent + guard ALREADY_MATCHED) = VERIFICADO-OK — `tests/test_u10_u11_concurrencia.py`. `suggest_matches` batcheado (1 query global, misma semántica) con las suites de comportamiento existentes como red golden (`test_bank_reconciliation*`, `test_reconciliation_e2e_consecuencia_bug`) |
| U12 — portfolio kernel | HECHO | **BUG-005** CERRADO (previo). Oleada 5: link_billing doble-CxC bajo CONCURRENCIA = VERIFICADO-OK con test de 2 hilos (5/5 corridas) + endurecido con `pg_advisory_xact_lock(company, doc)` (el chequeo filter-first tenía ventana teórica y Receivable no tiene constraint único por referencia — patrón BUG-004/008). accrue_interest idempotente y write_off (auditoría + RBAC) ya certificados por suites existentes (`test_portfolio_services`, `test_portfolio_rbac`). Cartera vencida ahora se filtra sargable en BD (outstanding con F()) y el último recordatorio por grupo va en 1 query (DISTINCT ON) |
| U13 — nomina: cálculo legal | EN-CURSO | Oleada 3: golden de EQUIVALENCIA del cómputo de planilla (masivo bulk == individual, campo por campo, perfiles mensual/jornalero/USD/sin-INSS) + punto fijo (recalcular no mueve nada) — `tests/test_golden_compute_sheet_bulk.py` = VERIFICADO-OK. `compute_all_entries_in_sheet` con UN bulk_update (updated_at fijado explícito) y tramos IR cacheados por instancia de config (antes: 1 query de tramos POR entrada). Falta: golden puntuales de INSS/IR contra tablas legales |
| U14 — nomina: rieles de pago | EN-CURSO | Oleada 3: ingesta biométrica con dedupe por LOTE (1 query de keys existentes + bulk_create; el duplicado intra-lote también se descarta) — misma semántica, cubierta por `tests/test_biometric*.py` verdes. Falta: certificación de pagos de planilla (register_payroll_payment bajo concurrencia) |
| U15 — nomina: asistencia campo | HECHO | Oleada 4: SoD maker≠checker ya certificado por suites existentes (`test_field_attendance_api/advanced`: self-approval bloqueado, permiso approve requerido, happy path con checker distinto); + 2 tests nuevos de idempotencia (`test_field_attendance_bridge.py`): re-consolidar no duplica y se BLOQUEA tras aprobar; re-aplicar a planilla deja los mismos días y neto (SET, no suma) con consolidaciones LOCKED_FOR_PAYROLL. UI completa del flujo (5 páginas, 15 huérfanos L4 cerrados). MEJORA pendiente anotada: el backend no expone GET de solicitudes SoD ni de cuadrillas/rollcall del día (la UI degrada a bitácora/localStorage) — candidato para una oleada futura |
| U16 — hr module | PENDIENTE | |
| U17 — compras | PENDIENTE | |
| U18 — ventas | PENDIENTE | (bug-hunt integridad: recepción no excede orden, POS no vende bajo stock, redondeo y numeración fiscal = VERIFICADO-OK; sin bug) |
| U19 — retail_pos + sync_engine | EN-CURSO | Oleada 7: `process_batch` con UNA transacción por chunk de 20 + savepoint explícito POR comando (antes: un commit/fsync por comando) — cualquier error de BD de un comando revierte solo su savepoint y el resto del chunk procesa; respuesta por comando y semántica de fallo idénticas. VERIFICADO-OK con las suites sync/POS completas (100 tests: contrato v2, comandos POS, retail_pos). Desviaciones documentadas: audit writes NO se bulkearon (write_event con encadenamiento — bulkear arriesga integridad de la bitácora); `run_retail_pos_edge_e2e.sh` requiere el perfil QA CI (contra el stack dev falla en login/Axes) — correr en `make qa-ci`. Falta: certificación profunda del kill-switch y firma de comandos |
| U20 — comisariato + intercompany + parties | EN-CURSO | Bug-hunt integridad: **BUG-018** (intercompany: doble cargo concurrente sin lock/constraint IC-1, posteo en período CERRADO IC-2, FX ignorado IC-3) y **BUG-020** (comisariato `collecting_company` cross-company sin gate CXC) CERRADOS con tests. Falta: resto de parties + consolidación profunda |
| U21 — reporting kernel | EN-CURSO | Oleada 6: adaptadores hr (headcount GROUP BY en BD, antes iteraba todo en Python) e inventory (stock/movimientos: totales agregados en BD + detalle values() con tope 5000 y warning) = VERIFICADO-OK con la suite reporting verde; cache TTL 45s SOLO para freshness CACHE_ALLOWED (LIVE_ONLY nunca cachea, SNAPSHOT_REQUIRED va por snapshots; copias profundas para no contaminar el cache); `reporting_registry_contract_guard` verde. DIFERIDO con razón: fuel.py (módulo dormido todo el demo — convertir cuando despierte, U27). Falta: certificación profunda de la unidad (quality/lineage/exports) |
| U22 — frontend core (boot/stores/router) | HECHO | Oleada 0: hot-spot U22-3 (interceptor expulsaba a /403 ante cualquier 403) CERRADO — flag `background` en axios (**BUG-006**); infra `useListadoServer` + `PageReq`. Oleada 7: poll del tablero con skip-si-no-cambió (sin re-render cada 60s si nada cambió); diccionario central de códigos (`core/codigos.ts` + `apiErrorMessage`, con tests) — códigos crudos traducidos a español con fallback honesto; 26 páginas en paginación server-side y las client-side restantes con comentario de decisión explícita. Certificado por typecheck/lint/vitest (20 tests) + guard L4 bloqueante |
| U23 — frontend auth/org/rbac/devices | PENDIENTE | |
| U24 — frontend hr/nomina/pagador | PENDIENTE | |
| U25 — frontend ventas/pos/billing | PENDIENTE | |
| U26 — frontend inv/proc/pay/portfolio/acct | EN-CURSO | Oleada 2: **BUG-009** (IntercompaniaPage usaba `id` pero el backend manda `tx_id` UUID → TODAS las acciones pegaban a `/transactions/undefined/` y el flujo intercompany por UI estaba muerto; preexistente de v2, destapado por la revisión adversarial) CERRADO. Tablas de intents, intercompany, existencias y kardex migradas a paginación server-side. Falta: resto de la unidad |
| U27 — estacion_servicios + fuel (dormido) | PENDIENTE | |
| U28 — finca/financiamiento/fleet/cec/beneficio (dormidos) | PENDIENTE | |
| U29 — knowledge/diagnostics/integration (dormidos) | PENDIENTE | |
| U30 — stubs y arrastre v2 | PENDIENTE | |

## Progreso — Lentes transversales (5)

| Lente | Estado | Veredicto (findings / IDs) |
|-------|--------|----------------------------|
| L1 — seguridad/authz (IDOR + self-auth) | EN-CURSO | Bug-hunt integridad: barrido de TODOS los ViewSets de escritura → arquitectura mayormente inmune (FKs resueltos scopeados en servicios), pero **BUG-019** (Receivable/Payable/Credit/Allocation ViewSets con FKs escribibles sin scope → IDOR de escritura, mismo patrón que BUG-011) CERRADO: los 4 pasan a ReadOnly. **BUG-020** (comisariato collecting_company) CERRADO. Falta: 14 endpoints self-auth. (BUG-011 se cierra en la rama aislamiento/PR-9) |
| L2 — concurrencia/idempotencia | EN-CURSO | Bug-hunt integridad: motor money-moving VERIFICADO-OK (post_journal_drafts, reverse, pay_payable, collect_receivable, allocate/BUG-005, secuencia fiscal — todos con lock/constraint citado). Huecos cerrados: **IC-1** (cargo intercompany sin lock/constraint), **BILL-1** (`create_payment` sin idempotencia por API directa). Falta: 14 self-auth |
| L3 — integridad contable | EN-CURSO | Bug-hunt integridad: asientos del motor SIEMPRE cuadran y son idempotentes (VERIFICADO-OK). Huecos del posteo DIRECTO de intercompany cerrados: **IC-2** (posteo en período CERRADO) e **IC-3** (FX ignorado → GL subvaluado para moneda ≠ NIO, ahora rechazado). Falta: FX real intercompany, revaluación profunda |
| L4 — calidad frontend | HECHO | Guard `qa/api_frontend_drift_guard.py` (drift api.ts ↔ urls.py) **BLOQUEANTE en CI** desde O7 (promesa de O0 cumplida). Baseline: 43 → **12** huérfanos a lo largo del programa (O1 pedidos-crédito, O2 accounting, O4 field/* completo, O5 portfolio, O6 reporting); los 12 restantes con razón honesta permanente (device-side, legacy, retrieves sin campos extra). **0 cableado roto** en todo el programa. L4b cerrada: diccionario central de códigos (O7) |
| L5 — drift v2↔v3 y arrastre | PENDIENTE | |

---

## Certificaciones "VERIFICADO-OK" (falsos positivos con mitigación probada)

> Cada entrada = un hot-spot que parecía bug pero tiene mitigación. Documentar DÓNDE está la
> mitigación (archivo:línea). Tiene valor de certificación — no se descarta en silencio.

| Hot-spot | Mitigación (archivo:línea) | Notas |
|----------|----------------------------|-------|
| `nomina/portfolio_link.py` — supuesto doble-cobro silencioso | NM-06 en `register_payroll_loan_deduction` (setea `abono_applied`, loguea `payroll_loan_abono_pending`) | Residual = MEJORA (falta cola de reintento/alerta), no bug |
| `boot/axios.ts` — supuesto refresh sin single-flight (logout espurio) | `auth.store.ts::refresh()` (guard `if (this.refreshInFlight) return`, con `refreshInFlight` asignado **sincrónicamente** justo después del guard) | Single-flight correcto → falsa alarma del diseño; N×401 disparan UN solo refresh |
| `inventarios/services.py::post_issue` — supuesto stock negativo (guard fuera del lock) | `_get_or_create_balance_locked` toma `select_for_update` (L844) ANTES del guard `InsufficientStockError` (L846) | Chequeo-luego-descuento serializado dentro del lock → correcto |
| `portfolio::apply_payroll_abono` / `reverse_payroll_abono` — supuesto over-allocation | lock `select_for_update` (L952/L1003) ANTES de leer `outstanding` y topar con `min()` | Patrón correcto (a diferencia de allocate_payment, que era BUG-005) |

---

## Findings (detalle) — usar el formato del runbook §4

> Los BUG confirmados se transcriben además a `BUGS.md` (BUG-004+) ANTES de arreglar. Acá va el
> detalle completo de cada finding (incluidas mejoras y decisiones).

_(vacío — completar durante la auditoría)_

---

## Informe final

_(completar al cerrar: bugs por severidad, mejoras, certificados-OK, BUG-IDs nuevos, riesgo residual)_
