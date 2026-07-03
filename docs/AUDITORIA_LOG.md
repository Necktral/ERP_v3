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
| U5 — accounting: posteo | PENDIENTE | |
| U6 — accounting: períodos/FX | PENDIENTE | |
| U7 — accounting: API | PENDIENTE | |
| U8 — inventarios kernel | HECHO | Oleada 1: **BUG-007** (idempotencia no comparaba el LOTE → falso match silencioso) encontrado por test y CERRADO con fix. Idempotency match warehouse/qty/lote = VERIFICADO-OK; `post_transfer` cruzado concurrente sin deadlock (lock ordenado) = VERIFICADO-OK — `tests/test_u8_idempotencia_y_transferencias.py` (6 tests). Costing/reversal/link contable cubiertos por suites existentes verdes (`test_cost_policy`, `test_movement_reversal`, `test_inventory_accounting_integration`). Guard `InsufficientStockError` = VERIFICADO-OK (previo) |
| U9 — facturacion kernel | EN-CURSO | Oleada 1: golden tests de fidelidad de líneas/totales byte-a-byte (`tests/test_golden_lineas_bulk.py`) escritos ANTES del refactor a bulk_create (create_draft/create_order) = VERIFICADO-OK; filtro de fechas sargable en listado de docs; budgets O(1)-en-líneas en `src/tests/perf/`. Falta: resto de la unidad (void SoD profundo, contingencia fiscal, secuencias) |
| U10 — payments: intents/caja/arqueo | PENDIENTE | |
| U11 — payments: conciliación | PENDIENTE | |
| U12 — portfolio kernel | EN-CURSO | **BUG-005** (over-allocation → outstanding negativo en `allocate_payment_to_obligation`) CERRADO con fix+test. `apply_payroll_abono`/`reverse_payroll_abono` = lock correcto (VERIFICADO-OK). Falta: link_billing doble-CxC, accrue_interest idempotencia, write_off |
| U13 — nomina: cálculo legal | PENDIENTE | |
| U14 — nomina: rieles de pago | PENDIENTE | |
| U15 — nomina: asistencia campo | PENDIENTE | |
| U16 — hr module | PENDIENTE | |
| U17 — compras | PENDIENTE | |
| U18 — ventas | PENDIENTE | |
| U19 — retail_pos + sync_engine | PENDIENTE | |
| U20 — comisariato + intercompany + parties | PENDIENTE | |
| U21 — reporting kernel | PENDIENTE | |
| U22 — frontend core (boot/stores/router) | EN-CURSO | Oleada 0: hot-spot U22-3 (interceptor expulsaba a /403 ante CUALQUIER 403, incluidos polls) CERRADO — flag `background` en axios + polling del tablero marcado (**BUG-006**). Infra de paginación server-side (`useListadoServer` + `PageReq`/`toPageParams`) con pilotos en billing (FacturacionPage) y accounting (DiarioPage). Falta: resto de la unidad |
| U23 — frontend auth/org/rbac/devices | PENDIENTE | |
| U24 — frontend hr/nomina/pagador | PENDIENTE | |
| U25 — frontend ventas/pos/billing | PENDIENTE | |
| U26 — frontend inv/proc/pay/portfolio/acct | PENDIENTE | |
| U27 — estacion_servicios + fuel (dormido) | PENDIENTE | |
| U28 — finca/financiamiento/fleet/cec/beneficio (dormidos) | PENDIENTE | |
| U29 — knowledge/diagnostics/integration (dormidos) | PENDIENTE | |
| U30 — stubs y arrastre v2 | PENDIENTE | |

## Progreso — Lentes transversales (5)

| Lente | Estado | Veredicto (findings / IDs) |
|-------|--------|----------------------------|
| L1 — seguridad/authz (IDOR + self-auth) | PENDIENTE | |
| L2 — concurrencia/idempotencia | PENDIENTE | |
| L3 — integridad contable | PENDIENTE | |
| L4 — calidad frontend | EN-CURSO | Oleada 0: guard automatizado `qa/api_frontend_drift_guard.py` (drift api.ts ↔ urls.py, ratchet+baseline): **0 cableado roto**; 43 huérfanos kernel baselineados con razón y oleada de cierre en `qa/contracts/api_frontend_drift_baseline.json`. `make qa-l4-drift`; en CI report-only (bloqueante desde O1). Falta: L4b (diccionario de códigos) |
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
