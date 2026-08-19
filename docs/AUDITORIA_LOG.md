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
| U1 — auth/accounts/2FA/bootstrap | HECHO | **BUG-004/028/029/030** CERRADOS. PostgreSQL real: refresh rotation con un solo descendiente, bootstrap init/org con un ganador y 2FA challenge single-use; matriz L2 21/21. Cookies/transporte y self-service cubiertos por suites accounts y matriz L1 de excepciones credencializadas. |
| U2 — iam contexto + middlewares | HECHO | JWTAuthWithOrgContext es la capa instalada; excepciones compartidas fail-closed y aislamiento P0 tenant/auth/integration/diagnostics: 189 tests tenant, matrices A/B y regresión auth. |
| U3 — rbac + org (módulos) | HECHO | Guard fresco: 306 escrituras, 292 con RBAC y 14 excepciones credencializadas exactas; matriz negativa 16/16, seeds y activación de módulos cubiertos. |
| U4 — audit + common | HECHO | Envelope/contexto y redactado cubiertos; prueba PostgreSQL con cuatro writers concurrentes conserva cadena lineal y un único head por partición. |
| U5 — accounting: posteo | HECHO | `post_journal_drafts` optimizado sin cambio de semántica. SoD/idempotencia y transición única bajo concurrencia PostgreSQL certificados; integrador L3 15/15 verde, incluidas regresiones **BUG-057/058**. |
| U6 — accounting: períodos/FX | HECHO | Períodos, cierre anual, revaluación y retry BLOCKED cubiertos por suites accounting; integrador L3 15/15 y BUG-058 cerrado. |
| U7 — accounting: API | HECHO | Permisos, tenant y actor cubiertos por suites accounting/phase5; GL agrega totales en BD, limita detalle y explicita truncamiento. Optimizaciones sólo se aceptaron con query budget medido. |
| U8 — inventarios kernel | HECHO | Oleada 1: **BUG-007** (idempotencia no comparaba el LOTE → falso match silencioso) encontrado por test y CERRADO con fix. Idempotency match warehouse/qty/lote = VERIFICADO-OK; `post_transfer` cruzado concurrente sin deadlock (lock ordenado) = VERIFICADO-OK — `tests/test_u8_idempotencia_y_transferencias.py` (6 tests). Costing/reversal/link contable cubiertos por suites existentes verdes (`test_cost_policy`, `test_movement_reversal`, `test_inventory_accounting_integration`). Guard `InsufficientStockError` = VERIFICADO-OK (previo). Bug-hunt integridad: **BUG-014** (transferencia no mezclaba el costo promedio del destino) y **BUG-016** (ajuste/conteo no tocaban `LotBalance` → Σ lotes ≠ saldo) encontrados por test y CERRADOS |
| U9 — facturacion kernel | HECHO | Golden de líneas/totales, filtros sargables y budgets O(1). **BUG-015/017/022/023/024/032/034** CERRADOS. PostgreSQL real: emisión fiscal concurrente con numeración única/contigua, colisión y agotamiento atómicos, contingencia/reintento/reconciliación sin renumerar; matriz L2 verde. |
| U10 — payments: intents/caja/arqueo | HECHO | Oleada 2: **BUG-008** (apertura de caja concurrente → IntegrityError crudo/500 en vez de 409 de dominio; el constraint único sostenía el invariante) encontrado por test y CERRADO. Cierre de caja concurrente no corrompe arqueo (lock + idempotencia) = VERIFICADO-OK — `tests/test_u10_u11_concurrencia.py`. Intents/estado/SoD/arqueo cubiertos por suites existentes verdes (`test_state_machines`, `test_cash_audit`, `test_payments_sod`, `test_opening_denominations`) |
| U11 — payments: conciliación | HECHO | Oleada 2: match concurrente del MISMO intent contra dos líneas → exactamente uno gana (lock del intent + guard ALREADY_MATCHED) = VERIFICADO-OK — `tests/test_u10_u11_concurrencia.py`. `suggest_matches` batcheado (1 query global, misma semántica) con las suites de comportamiento existentes como red golden (`test_bank_reconciliation*`, `test_reconciliation_e2e_consecuencia_bug`) |
| U12 — portfolio kernel | HECHO | **BUG-005** CERRADO (previo). Oleada 5: link_billing doble-CxC bajo CONCURRENCIA = VERIFICADO-OK con test de 2 hilos (5/5 corridas) + endurecido con `pg_advisory_xact_lock(company, doc)` (el chequeo filter-first tenía ventana teórica y Receivable no tiene constraint único por referencia — patrón BUG-004/008). accrue_interest idempotente y write_off (auditoría + RBAC) ya certificados por suites existentes (`test_portfolio_services`, `test_portfolio_rbac`). Cartera vencida ahora se filtra sargable en BD (outstanding con F()) y el último recordatorio por grupo va en 1 query (DISTINCT ON) |
| U13 — nomina: cálculo legal | HECHO | Golden masivo==individual, punto fijo, perfiles mensual/jornalero/USD/sin-INSS y tramos legales. Integrador dirigido 15/15 verde; **BUG-057/058** cerrados con regresión. El visto bueno profesional sobre tablas legales permanece como riesgo humano, separado del cierre técnico. |
| U14 — nomina: rieles de pago | HECHO | Biometría deduplicada por lote y token hasheado. PostgreSQL real: ocho pagos simultáneos con misma clave dejan una consecuencia; claves distintas nunca sobrepagan el neto. Matriz L2 verde. |
| U15 — nomina: asistencia campo | HECHO | SoD maker≠checker, consolidación/aplicación idempotentes y bloqueo post-aprobación certificados. GET tenant-scoped persistente de rollcall, cuadrillas y solicitudes SoD; UI eliminó fallback `localStorage`/bitácora. Backend 2/2, frontend 2/2 y typecheck dirigido verdes. |
| U16 — hr module | HECHO | Ciclo empleado/party/roles, contratos, firma/renovación, vacaciones, lifecycle, uploads y revocación cubiertos; BUG-002 incluye cross-tenant, fail-closed, replay y concurrencia. |
| U17 — compras | HECHO | PostgreSQL real: numeración de documentos y órdenes sin duplicados, recepción concurrente serializada con inventario consistente y pagos CxP con claves distintas sin sobrepago; matriz L2 verde. |
| U18 — ventas | HECHO | Recepción no excede orden, POS no vende bajo stock, redondeo/numeración = VERIFICADO-OK. Venta POS concurrente con la misma clave produce un documento, un descuento de stock y un movimiento de caja; matriz L2 verde. |
| U19 — retail_pos + sync_engine | HECHO | Sync/POS conserva savepoint por comando. Certificación HTTP fresca en stack forense: edge firmado 201, replay 409 `REPLAY_DETECTED`, firma inválida 401 `BAD_SIGNATURE`, capabilities 200; pilot smoke y rollback `passed`, kill-switch de terminal revocada 403 `DEVICE_REVOKED`. Trazas redactan credenciales. |
| U20 — comisariato + intercompany + parties | HECHO | BUG-018/020 cerrados; suites cubren crédito, rectificación, tenant gate, concurrencia/período/moneda, consolidación, disputa/settlement y normalización/scope de parties. BUG-057 asegura rechazo FX fail-closed. |
| U21 — reporting kernel | HECHO | Agregación en BD, límites de detalle, cache por freshness y contratos registry certificados. Token embed revalida RBAC/revocación y bajo concurrencia permite exactamente un canje persistido; matriz L2 verde. Fuel dormido se conserva fuera de este corte y pertenece a U27. |
| U22 — frontend core (boot/stores/router) | HECHO | Oleada 0: hot-spot U22-3 (interceptor expulsaba a /403 ante cualquier 403) CERRADO — flag `background` en axios (**BUG-006**); infra `useListadoServer` + `PageReq`. Oleada 7: poll del tablero con skip-si-no-cambió (sin re-render cada 60s si nada cambió); diccionario central de códigos (`core/codigos.ts` + `apiErrorMessage`, con tests) — códigos crudos traducidos a español con fallback honesto; 26 páginas en paginación server-side y las client-side restantes con comentario de decisión explícita. Certificado por typecheck/lint/vitest (20 tests) + guard L4 bloqueante |
| U23 — frontend auth/org/rbac/devices | HECHO | Backend auth/bootstrap/devices y browser login/contexto/RBAC; almacenamiento seguro, TTL y reconexión. Playwright por rol y offline aprobado. |
| U24 — frontend hr/nomina/pagador | HECHO | Suites HR/nómina/asistencia/pagador y browser/axe en pantallas críticas, tres viewports; persistencia SoD real sin localStorage. |
| U25 — frontend ventas/pos/billing | HECHO | Suites ventas/POS/billing, rol cajero, offline/reconexión y guard de doble envío; smoke autenticado sin 5xx. |
| U26 — frontend inv/proc/pay/portfolio/acct | HECHO | Suites de kernels consumidores, paginación remota, axe en inventario y navegación browser; checkboxes accesibles y cero rutas rotas. |
| U27 — estacion_servicios + fuel (dormido) | HECHO | Suite backend U27–U29 (392 aprobadas, 1 omitida contractual) y módulos habilitados sólo en fixture forense; smoke browser sin 403/5xx. |
| U28 — finca/financiamiento/fleet/cec/beneficio (dormidos) | HECHO | Backend dirigido MEJ-009/011 26/26, búsqueda/paginación tenant-scoped y smoke browser autenticado. |
| U29 — knowledge/diagnostics/integration (dormidos) | HECHO | Suite backend integral compartida y smoke browser autenticado sin 5xx; diagnostics/integration conservan scope tenant. |
| U30 — stubs y arrastre v2 | HECHO | Inventario firmado de 7 superficies y 305 deltas: 0 productivos inexplicados; `DEMO_PING` bloqueado en prod y probado. |

## Progreso — Lentes transversales (5)

| Lente | Estado | Veredicto (findings / IDs) |
|-------|--------|----------------------------|
| L1 — seguridad/authz (IDOR + self-auth) | HECHO | **BUG-019/020** y aislamiento P0 cerrados. Guard fresco: 306 escrituras, 292 RBAC, exactamente 14 excepciones versionadas, cero drift; matriz adversarial 16/16 demuestra fail-closed y aislamiento A/B/self-service. |
| L2 — concurrencia/idempotencia | HECHO | Matriz PostgreSQL real 21/21: refresh, bootstrap, 2FA, POS, inventario, caja/conciliación, nómina, reporting token, posteo, compras/CxP y numeración fiscal. Un ganador/una transición o rechazo controlado en cada caso; sin corrupción ni sobrepago. |
| L3 — integridad contable | HECHO | Asientos balanceados/idempotentes, períodos/SoD/fault paths e intercompany endurecidos. Integrador dirigido 15/15 verde; **BUG-057/058** cerrados. FX comercial completo y visto bueno profesional permanecen como riesgo residual explícito, no como código pendiente de este lente técnico. |
| L4 — calidad frontend | HECHO | Drift fresco: 508 rutas, 388 llamadas, 0 rotas y 13 huérfanos justificados. Playwright 4/4: roles, 19 dominios, axe sin serious/critical en login+6 pantallas×3 viewports, foco y offline/reconexión. |
| L5 — drift v2↔v3 y arrastre | HECHO | `v2_v3_drift_inventory.json`: 305 deltas clasificados, 0 productivos inexplicados; reachability/auth/disposition y responsable por superficie. |

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

**PASS técnico:** 30/30 unidades y 5/5 lentes cerrados. La estabilización final añadió BUG-065..069
(throttling global, contexto Docker, Node de producción, deuda Mypy y UUID del POS), todos cerrados.
La certificación de referencia registra 2,071 pruebas backend sin fallos/errores y un único skip
contractual, frontend lint/typecheck/build y Vitest verdes, Playwright 4/4, migración desde base
vacía y guards de arquitectura, gobernanza, seguridad, RBAC y contratos aprobados. Los vistos
buenos profesionales y las excepciones de dependencias versionadas permanecen como riesgos
residuales explícitos; no se modificó el demo ni `ERP_v2`.
