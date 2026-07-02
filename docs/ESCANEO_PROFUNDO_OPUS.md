# Escaneo profundo de ERP_v3 — Runbook para Opus 4.8

> **Qué es este documento.** Un runbook **auto-contenido** para ejecutar la auditoría profunda de
> bugs + mejoras de ERP_v3 **en frío**, sin depender de ningún historial de chat. Lo escribió una
> sesión previa (Fable 5) que diseñó la auditoría completa pero **no pudo ejecutarla**: la flota
> multi-agente topó el límite de sesión 3 veces. Vos (Opus 4.8) la ejecutás con este mapa.
>
> **Regla de oro del proyecto:** todo bug se **documenta en `BUGS.md` ANTES de arreglarlo**. No se
> ablandan tests para que pasen. Los fixes van con test de regresión. Commit local sí, **push NO**.

---

## 0. Primeros pasos (arrancá acá)

Antes de leer el resto, ejecutá esta secuencia — son tus primeros movimientos, sin ambigüedad:

1. **Confirmá el stack arriba:** `docker compose ps` desde `~/dev/ERP_v3` — deben estar
   `erpcrm_db`, `erpcrm_backend`, `erpcrm_frontend` en `healthy`/`running`. Si no, `docker compose
   up -d --no-deps db backend frontend` (sin `dash_analytics`).
2. **Fijá el baseline de drift:** corré el `diff -rq` de §3. HOY solo debería listar
   `frontend/src/stores/auth.store.ts` + el tooling repuesto (`qa/`, `requirements/`, `ruff.toml`,
   `mypy.ini`, `.env`, este `docs/`). Anotá esa lista: es tu línea base — todo delta NUEVO que
   aparezca después tiene que corresponder a un BUG-ID.
3. **Abrí el registro:** creá/abrí `docs/AUDITORIA_LOG.md` (§11). Ahí vas a anotar el veredicto de
   CADA unidad y lente (incluidos los "verificado-OK"), y lo actualizás **después de cada unidad** —
   así un reset de cuota no borra tu progreso y podés retomar desde ahí.
4. **Arrancá la ola 1, unidad U1, hot-spot 1:** abrí `backend/src/apps/modulos/accounts/views.py`,
   ubicá `BootstrapInitView` (buscalo por nombre, no por línea) y verificá si el chequeo
   `User.objects.exists()` → `create_user` es atómico bajo dos POST concurrentes. Registrá el
   veredicto en `AUDITORIA_LOG.md`. Seguí con el hot-spot 2, y así.

**Modalidad recomendada:** inline en el main-loop (§2 opción A) — sin fan-out de sub-agentes, que
fue lo que reventó la cuota. Una unidad a la vez, checkpoint tras cada una.

---

## 1. Situación y objetivo

**Proyecto:** ERP/CRM Django 5 + DRF (backend) y Vue 3 + Quasar + Pinia (frontend), dockerizado.
Reconstrucción limpia para Agrícola Santa Isabel (holding cafetalero, Nicaragua). Arranca módulo
por módulo con **una sola empresa demo**. `../ERP_v2` es la referencia **solo lectura** (v3 es copia
fiel de v2 salvo un fix; ver §6).

**Ya hecho (no repetir):**
- **Fase 0 completa:** se repuso `qa/` de v2 (BUG-003 cerrado); **la suite backend está VERDE**
  (todos los tests pasan, 1 skip). `requirements/` y `.env` de raíz ya repuestos.
- **Paso 1 del ROADMAP DONE:** entorno levantado (DB vacía), empresa creada por el wizard real
  (Holding *Agrícola Santa Isabel* → Empresa *Comisariato Santa Isabel* → Sucursal *Casa Matriz*,
  moneda NIO). **BUG-001 cerrado** (rebote post-wizard a /login, fix en `auth.store.ts`).
- **BUG-002 abierto** (media, decisión de diseño): el admin del bootstrap es superusuario
  permanente, no "temporal que se desactiva" — a resolver en el paso 3 (HR).
- **Paso 2 (contabilidad base) DOING:** en prueba manual por UI.

**Lo que falta (TU trabajo):**
1. **Fase 1 — Auditoría:** revisar las **30 unidades + 5 lentes** (§7-§8), verificando cada hallazgo
   adversarialmente (§4).
2. **Fase 2 — Fixes:** aplicar **solo crítico/alto**, cada uno `BUGS.md` primero + test de
   regresión + commit local. Medios/bajos se documentan sin arreglar.
3. **Fase 3 — Regresión:** suite completa + smoke E2E + `diff -rq` v2↔v3 (cada delta ↔ un BUG-ID).

---

## 2. Cómo ejecutar sin topar el límite de sesión

**Lección aprendida:** lanzar los **35 agentes de golpe** (fan-out del Workflow) fue lo que reventó
la cuota tres veces seguidas. No lo repitas igual.

**Opciones, de menos a más riesgo de cuota:**

- **(A) Inline en el main-loop, unidad por unidad** (recomendado si la cuota está ajustada): abrís
  vos mismo los archivos de cada unidad, aplicás el checklist de hot-spots, y verificás. Sin
  sub-agentes. Lento pero imparable. Ideal para las olas 1-3 (plataforma + contabilidad + nómina),
  que son las de mayor riesgo y las que el demo toca primero.
- **(B) Lotes chicos de sub-agentes** (3-4 por vez, ola por ola): un `parallel()` de ≤4 revisores
  por tanda, esperás, seguís. Mantené el paralelismo bajo. Verificación adversarial en la misma
  tanda o en una segunda pasada.
- **(C) Reanudar el Workflow ya cacheado** — **OJO: solo sirve si continuás la MISMA sesión** donde
  se lanzó (el caché del Workflow es *same-session-only*). Una sesión Opus **nueva** NO puede usar
  `resumeFromRunId: "wf_f44e8960-8d3"` — el caché no existe para ella, así que reanudar re-correría
  todo de cero **y volvería a fanoutear** (fue lo que reventó la cuota 3 veces). **Para un Opus
  fresco: no uses C, usá (A) inline o (B) lotes chicos.** C solo aplica si sos la misma sesión con
  cuota fresca.

**Orden de olas (prioridad, §8):** 1 plataforma → 2 accounting → 3 HR/nómina → 4 inventario/compras/
cartera → 5 ventas/POS/caja/pagos → 6 frontend → 7 reporting+lentes → 8 verticales dormidos.

---

## 3. Arnés de verificación (comandos exactos)

El stack ya corre en docker (contenedores `erpcrm_db`, `erpcrm_backend`, `erpcrm_frontend`). Todos
los comandos desde `~/dev/ERP_v3`.

```bash
# Suite backend completa (baseline HOY = VERDE; cualquier rojo nuevo es tuyo)
docker compose exec -T backend bash -lc \
  "cd /app/backend && DJANGO_SETTINGS_MODULE=config.settings.test pytest -q"

# Suite dirigida de una app/kernel (usar en cada fix; incluir SIEMPRE src/tests)
docker compose exec -T backend bash -lc \
  "cd /app/backend && DJANGO_SETTINGS_MODULE=config.settings.test pytest src/apps/kernels/<app> src/tests -q"

# Lint / typecheck / seguridad backend (ruff.toml y mypy.ini ya repuestos)
docker compose exec -T backend bash -lc "cd /app/backend && ruff check src/"
docker compose exec -T backend bash -lc "cd /app/backend && mypy src/"
docker compose exec -T backend bash -lc "cd /app/backend && bandit -r src/"

# Guards de QA (ya presentes tras reponer qa/) — p. ej. authz por ruta
docker compose exec -T backend bash -lc "cd /app && python qa/route_authz_guard.py"

# Frontend: lint + typecheck + vitest + build (servicio del compose, profile qa)
docker compose --profile qa up frontend_ci

# Drift v2↔v3 (cada archivo distinto DEBE mapear a un BUG-ID cerrado)
diff -rq ~/dev/ERP_v2 ~/dev/ERP_v3 \
  --exclude=__pycache__ --exclude=node_modules --exclude=.git --exclude='*.pyc'
```

> **🛑 NO TOQUES LA DB VIVA (`erpcrm_db`).** El usuario está en **prueba manual del paso 2
> (contabilidad)** con datos vivos (holding/empresa/sucursal + lo que vaya cargando). Un
> `manage.py flush` o un `docker compose down -v` **le borra ese trabajo**. `pytest` es seguro (usa
> su propia DB de test, `config.settings.test`), pero el smoke E2E del bootstrap NO va contra la DB
> viva.

**Smoke E2E del bootstrap** (cobertura real del fix BUG-001; obligatorio si tocás `stores/`,
`router/`, `boot/` o `accounts/`): sobre **DB efímera aislada**, nunca la viva. Cómo levantar el
stack efímero sin tocar el vivo (proyecto docker separado, volumen y puertos propios):

```bash
# Stack aislado en un proyecto docker aparte (-p) con puertos distintos y su propio volumen.
# Ajustá los puertos si están ocupados. NO comparte la DB con erpcrm_db.
docker compose -p erpv3_smoke \
  -f compose.yaml \
  up -d --no-deps db backend frontend
# ... correr el wizard con agent-browser contra el frontend efímero ...
docker compose -p erpv3_smoke down -v   # destruye SOLO el stack efímero
```

Flujo a verificar: wizard → crear admin → holding/empresa/sucursal → "ENTRAR AL SISTEMA" y confirmar
que cae en `/#/tablero` **sin rebote a `/login`**. Se maneja con `agent-browser`
(`npx --no-install agent-browser open <url-efímera>`, `snapshot`, `fill @ref`, `click @ref`).
*(Si el compose no parametriza puertos por env, alcanza con un `compose.override` que remapee
`5432/8000/3000`; lo importante es el `-p erpv3_smoke` + `down -v` propio.)*

---

## 4. Protocolo de hallazgos

**Formato de finding (uno por hallazgo):**

```
FIND-<unidad>-<n>   (ej. FIND-U19-3)
Archivo:línea       backend/src/apps/modulos/sync_engine/services.py:317
Severidad           crítico | alto | medio | bajo
Invariante          1-6 (o "ninguno" si es calidad)
Clasificación       BUG | MEJORA | FALSO-POSITIVO | DECISIÓN-DE-DISEÑO
Escenario concreto  estado inicial → acción → resultado observado vs esperado (reproducible)
Evidencia           cita textual del código + (si aplica) test que lo contradice/cubre
Fix propuesto       cambio mínimo + test de regresión sugerido
Riesgo del fix      qué suites correr (apps afectadas)
```

**Severidad:**
- **Crítico** — viola un invariante 1-5 con escenario alcanzable (descuadre contable, IDOR entre
  empresas, doble cobro/pago, neto legal descontado, escritura directa sin draft) o RCE/escalada.
- **Alto** — corrupción de datos recuperable, bloqueo de un paso del demo, **pérdida silenciosa de
  operación** (patrón `except: return None`).
- **Medio** — robustez (race improbable pero real, error sin traducir en flujo principal, doble
  submit).
- **Bajo** — calidad, N+1 tolerable, código muerto, naming.

**Clasificación (verificación adversarial — clave):** un hallazgo es **BUG real** solo si trazás la
ruta COMPLETA request→código **sin encontrar la mitigación**, y el escenario es ejecutable con el
producto actual (una empresa, módulos del demo). Si la mitigación existe en otra capa, es
**FALSO-POSITIVO** y se documenta **dónde** está la mitigación (no se descarta en silencio: queda
como "verificado-OK", tiene valor de certificación). **MEJORA** = correcto pero frágil/confuso/lento.
**DECISIÓN-DE-DISEÑO** = divergencia con la constitución que decide el dueño (como BUG-002).

**Flujo:** finding → dedupe (los lentes L1-L3 pisan unidades) → los **BUG confirmados** se
transcriben a `BUGS.md` con la plantilla (BUG-004, BUG-005, …) **ANTES** de tocar código → test de
regresión que falla antes/pasa después → fix mínimo → suite dirigida → **commit local atómico**
referenciando el BUG-ID (NO push) → mover a "Bugs cerrados" con causa raíz.

---

## 5. Los 6 invariantes de negocio (verificalos explícitamente)

1. **Net legal de nómina inviolable** — la ley nicaragüense prohíbe descontar comisariato/deudas de
   la planilla; el cobro va aparte vía portfolio DESPUÉS del cierre. Complemento salarial excluido
   de base INSS (net=gross). Enforced en `kernels/nomina/models.py:788` (campos
   `store_credit_deduction`/`loan_payment` inertes en el neto).
2. **Doble partida** — todo asiento cuadra (débitos=créditos); pipeline `EconomicEvent → JournalDraft`
   (maker-checker) `→ JournalEntry`; períodos con close/reopen auditado. `kernels/accounting/services.py`.
3. **Aislamiento multi-tenant** — headers `X-Company-Id`/`X-Branch-Id`; la empresa B jamás lee/muta
   datos de A (IDOR); `rbac_permission` aplicado en cada escritura. `common/permissions.py` +
   `iam/context_middleware.py`.
4. **Idempotencia** — riel sync offline (POS), pagos, movimientos de inventario; comando REJECTED no
   reintentable; doble idempotencia del sync.
5. **Draft-first** — nada escribe directo a tablas críticas sin revisión (buscar `JournalEntry.objects.create`
   fuera de `post_journal_drafts`).
6. **Simplicidad usuario del campo** (frontend) — mensajes en español claros (no códigos crudos),
   validaciones que guían, flujos lineales, estados carga/error/vacío, responsive tablet.

---

## 6. Restricciones duras

- **`../ERP_v2` es solo lectura.** Nunca escribir ni commitear ahí. v3 es byte-idéntico a v2 salvo
  `frontend/src/stores/auth.store.ts` (fix BUG-001) + el tooling repuesto — por eso `diff -rq` es un
  detector de drift barato: todo delta debe corresponder a un BUG-ID.
- **No borrar módulos dormidos** (fleet, beneficio, financiamiento, fuel, cec, finca, estación):
  rompen imports (`sync_engine/registry.py` registra sus handlers). Se auditan, no se borran.
- **`auth.store.ts` intocable** salvo para AGREGAR un test de vitest que congele el contrato de
  BUG-001 (hoy `stores/__tests__` es el único guardián).
- **Push deshabilitado** hasta que el repo v3 sea privado (hoy es público). Commit local sí.
- **No ablandar tests.** Un test rojo es un bug del código, no del test.
- **DB viva intocable** (`erpcrm_db`): el paso 2 está en prueba manual con datos vivos. Nada de
  `flush`/`down -v` sobre el stack vivo; el smoke E2E va en stack efímero aparte (§3).

---

## 7. Catálogo de las 30 unidades de revisión

Cada unidad = un foco de revisión. LOC aprox sin migraciones/tests.

> **⚠ Los hot-spots son HIPÓTESIS, no bugs confirmados.** Salieron de una pasada de **lectura** del
> código real (diseño), pero la verificación adversarial **nunca corrió** — por eso existís vos. Tratá
> cada hot-spot como una **pista a verificar** (§4), no como un hecho. **Buscá por nombre de símbolo,
> no por número de línea:** las líneas son aproximadas y pueden haber drifteado. Si al trazar la ruta
> encontrás la mitigación, es **FALSO-POSITIVO** → registralo como "verificado-OK" en
> `AUDITORIA_LOG.md` (tiene valor de certificación), no lo descartes en silencio.

### FASE A — Plataforma transversal

**U1 — Auth: accounts + cookies + 2FA + bootstrap** · `backend/src/apps/modulos/accounts/` (~2.000)
1. `views.py:972 BootstrapInitView` — chequea `User.objects.exists()` y luego `create_user` **sin
   lock/transacción visible**: dos POST concurrentes en DB fresca → dos admins. Verificar atomicidad.
2. `views.py:440-447 _consume_2fa_challenge` — `delete()` dentro de `atomic()`: confirmar
   `select_for_update` sobre `TwoFactorChallenge` (replay bajo concurrencia).
3. `RefreshView` (452) — rotación de refresh: ¿el token viejo queda revocado o reusable?
4. `cookies.py` + `_require_secure_cookie_transport` — flags Secure/HttpOnly/SameSite; env
   `AUTH_ALLOW_TRANSPORT_OVERRIDE=1` en compose (¿qué habilita en prod?).
5. Throttles — que TODOS los AllowAny tengan throttle real en settings.
6. BUG-002: mapear superficies donde `is_superuser` bypasea RBAC.

**U2 — IAM: contexto multi-tenant + middlewares** · `modulos/iam/` (~2.550) + `config/middleware/`
1. **Doble capa de contexto:** `OrgContextMiddleware` vs `JWTAuthWithOrgContext` — rutas donde solo
   corre una (DRF auth corre DESPUÉS del middleware): ¿`request.company` de una capa y `data_company`
   de otra?
2. `context_middleware.py:63-75` — membresía a company habilita **cualquier** branch de esa company:
   ¿intencional? Documentar.
3. `EXEMPT_PATH_PREFIXES` (`iam/context.py:12-33`) — rutas dobles `/api/` y `/api/v1/`: comparar
   contra `urls.py` real por drift (ruta operativa que matchee un prefijo exento = agujero).
4. `device_guard.py` (kill-switch REVOKED) — orden en MIDDLEWARE (¿corre antes de auth? ¿se puede
   spoofear `X-Device-Id` inexistente para evadir bitácora?).
5. `iam/bootstrap.py` + `management/commands/bootstrap_company.py` — unicidad/rollback.

**U3 — RBAC + org (catálogo de módulos)** · `modulos/rbac/` (~2.800), `modulos/org/` (~2.650), `common/permissions.py`
1. `rbac/selectors.py::get_effective_permissions_for_scope` — se invoca por request y a veces dos
   veces (`ventas/views.py:103`): costo y coherencia.
2. `common/permissions.py:94-100` — enforcement intercompany solo READ y solo si `data_company != company`,
   pero el middleware setea `data_company=company` siempre. ¿Quién setea un `data_company` distinto?
   Si nadie, rama muerta con falsa sensación de cobertura.
3. Drift permiso-string — cruzar todos los `rbac_permission("...")` contra `rbac/seed_v01.py` (un
   typo = permiso que ningún rol tiene = deny permanente, o al revés).
4. `org/services_modules.py` + `module_catalog.py` — **¿la activación de módulos por empresa se
   aplica en backend** (denegar endpoints de módulos apagados) o solo esconde nav en frontend?
5. `RBAC_INCLUDE_GLOBAL_USERROLES` (`permissions.py:81`) — semántica y default.

**U4 — audit + common (bitácora + envelope de errores)** · `modulos/audit/` (~3.100), `common/` (~1.540)
1. `audit/writer.py` — cadena de hash (`_hmac_hex`): origen de la HMAC key; si `write_event` falla,
   ¿aborta la operación o traga? (ambos son hallazgo según el caso).
2. `AuditAccessDeniedMiddleware` — que denegaciones de middleware (no DRF) también auditen.
3. Envelope de errores (`build_error_envelope`) — consistencia para que el frontend traduzca (L4).
4. `select_for_update` en audit — ¿serializa la cadena por partición y a qué costo?

### FASE B — Kernels (ruta crítica contable)

**U5 — accounting: pipeline de posteo** · `kernels/accounting/services.py` (3.426), `models.py` (1.097)
1. `post_journal_drafts` (2242) — SoD "mismo aprobador no postea" **solo si `actor_user is not None`**
   (~2288): batch/automáticas sin actor evaden SoD. Trazar call sites de `auto_approve`/`allow_same_approver`.
2. Balance — comparar que en `_post_single_journal_draft`/`link_operational_event_to_accounting`
   (448/530) los totales SIEMPRE se recomputan de las líneas y la suma redondeada (`_q_money`, 2 dec)
   no deriva del total (drift de redondeo por línea).
3. `JournalEntry.objects.get_or_create(draft=...)` (2346) — idempotencia; ¿entry creado y luego
   falla la escritura de líneas → entry sin líneas?
4. `_period_for_occurrence` — ¿auto-crea `FiscalPeriod` para fechas arbitrarias? (período fantasma).
5. `_select_active_rule_set`/`_register_projection_exception` (409/882) — evento sin regla: ¿excepción
   visible o pérdida silenciosa?
6. `dispatch_accounting_outbox_events` (728) + `_lock_or_create_inbox` (1336) — exactly-once
   síncrono; **no hay `on_commit` en el repo**: ¿qué pasa si el caller hace rollback tras dispatch?

**U6 — accounting: períodos, year-end, FX, presupuestos** · `services.py` (close 2454, reopen 2630), `services_yearend.py`
1. Gates de cierre (`PeriodCloseGateEvaluation` 1869) — ¿bloquea con drafts sin postear/eventos sin
   linkear?
2. Reopen auditado — quién puede; posteos entre close→reopen→close consistentes.
3. Year-end (`YearEndClosing`) — leer `test_year_end_invariants.py`: qué cubre, qué borde queda.
4. `FxRate`/`RevaluationRun` — revaluación idempotente por corrida, reversión.
5. `certification*.py` (4 archivos ~1.500 LOC) — ¿vivo o arrastre de v2? Documentar, no borrar.

**U7 — accounting: API (views/serializers)** · `kernels/accounting/views.py` (1.448)
1. 32 vistas vs 36 refs de permiso — mapear una a una; ninguna vista de escritura con solo
   `IsAuthenticated`.
2. List endpoints filtran por `request.company` (IDOR) y sin N+1 sobre `JournalEntryLine`.
3. Serializers — `company`/`branch`/`state` no escribibles desde payload.
4. Aprobación/posteo — pasar `actor_user=request.user` SIEMPRE (conecta con U5-1).

**U8 — inventarios kernel** · `kernels/inventarios/` (~6.550)
1. `_assert_*_idempotency_match` (352-524) — comparación incluye warehouse/branch/lot (colisión de
   key con payload igual en OTRA sucursal debe ser conflicto).
2. `post_transfer` (1076) — orden de locks entre dos warehouses: deadlock si dos transferencias
   inversas concurrentes (`_get_or_create_balance_locked` 258).
3. `costing.py` — avg cost bajo receive/issue concurrente; costo negativo; redondeos.
4. `InsufficientStockError` — ¿el guard corre dentro del lock? (chequeo-luego-descuento fuera de
   lock = stock negativo).
5. `reversal.py` — reversa de reversa; reversa de movimiento ya contabilizado.
6. `_link_accounting_for_movement` (561) — ¿try/except tragando errores del link? (movimiento sin
   asiento = viola invariante 2).

**U9 — facturacion kernel** · `kernels/facturacion/` (~7.150)
1. `_allocate_document_number` (421) — correlativo por serie bajo concurrencia: `select_for_update`
   sobre el contador (dup/gap de numeración fiscal).
2. `issue_doc` (476) — emisión + print job + link contable ¿misma txn? Falla del adapter fiscal a
   mitad → `mark_doc_contingency`/`resolve_doc_contingency` consistentes.
3. `void_doc` (1111) + `void_sod.py` — SoD de anulación; anular doc con CxC ya cobrada.
4. `credit_notes.py` + restock — NC parcial doble sobre la misma factura.
5. `urls_legacy.py` — permisos consistentes entre ruta nueva y legacy.

**U10 — payments kernel: intents + caja + arqueo** · `kernels/payments/services.py` (~3.500 foco)
1. Máquina de estados intent (capture 221, reverse 316, refund 1095, cancel 1013) — transiciones
   inválidas bajo concurrencia (17 `select_for_update`; ¿falta authorize?).
2. `_idempotent_cash_movement_or_conflict` (576) — misma key con payload distinto = conflicto.
3. `close_cash_session_for_scope` (783) — cierre vs movimiento concurrente: ¿lock de sesión?
4. `reopen_cash_session_for_investigation` (1300) — permiso + auditoría.
5. `submit_denomination_count` (1260) — totales por denominación vs total de sesión (arqueo, paso 8).

**U11 — payments: conciliación bancaria** · `kernels/payments/reconciliation.py`, `views_reconciliation.py`
1. Vistas `get_permissions` dinámico (76-108) — mapeo read/write por método.
2. `match/unmatch/exclude` (176-227) — re-match de línea ya conciliada.
3. `test_reconciliation_e2e_consecuencia_bug.py` — leerlo: documenta un bug de v2; ¿vino el fix?

**U12 — portfolio kernel** · `kernels/portfolio/` (~5.660)
1. **Solo 3 `select_for_update` en TODO portfolio** (vs 17 en payments): `allocate_payment_to_obligation`
   (773) y `apply_payroll_abono` (935) concurrentes sobre la misma obligación → saldo negativo/doble
   abono. **Sospechoso #1 del kernel.**
2. `views.py:47-62 _rbac_perms` — que TODAS las actions (incl. `@action` custom, `InterestAccrualViewSet`)
   caigan en el mapa read/write.
3. `link_billing_document_to_receivable` (209) — doc facturado dos veces → ¿dos CxC?
4. `accrue_interest_for_credit` (1113) — idempotencia por período de devengo (doble corrida = doble
   interés).
5. `write_off_receivable` (354) — permiso propio + asiento de castigo.

**U13 — nomina: cálculo legal (INVARIANTE 1)** · `kernels/nomina/models.py` (`compute_all` 650-830)
1. **Invariante 1:** `models.py:788` — campos `store_credit_deduction`/`loan_payment` inertes en el
   neto. Test dirigido: setear ambos y verificar neto intacto (`test_nomina_business_invariants.py`).
2. `models.py:757/805` — ALIMENTOS suma al neto DESPUÉS de INSS/IR (no a base gravable); bordes con
   IR por brackets.
3. `services_inss.py` — régimen INSS **fechado**: cambio de régimen a mitad de período.
4. Complemento — excluido de base INSS/IR; `SalaryComplementSheet` con SoD ("quien envía no aprueba").
5. `models.py:823 NM-07` — costo patronal desde devengado bruto; que ningún reporte use el neto.
6. Séptimo día y feriados — semana con falta + feriado.

**U14 — nomina: rieles de pago y puentes** · `payroll_payments.py`, `portfolio_link.py`, `accounting_link.py`
1. `payroll_payments.py:108-128 register_payroll_payment_idempotent` — idempotencia + guard de
   sobrepago "dentro del lock pesimista" (verificar con `test_payroll_payment_concurrency_robustez.py`;
   buscar el mismo patrón SIN lock en otros rieles).
2. `portfolio_link.py:42 _apply_to_portfolio` — traga `PortfolioDomainError/ValueError/RuntimeError/TypeError`.
   **Ver §9: ya verificado — mitigado por NM-06 (no es silencioso), residual = MEJORA.**
3. `close_period` (129) — ¿exige `_period_fully_paid`? ¿link contable antes o después del cierre?
4. `pay_room.py:183` — expone `store_credit_deduction` informativo: la UI del pagador lo presenta
   como cobro separado, no descuento (invariante 1 en pantalla).

**U15 — nomina: asistencia de campo + biométrico** · `nomina/services.py` (418-1620), `field/`, `biometric/`
1. `consolidate_field_attendance` (1022-1222) — transferencias entre cuadrillas el mismo día; doble
   evento por trabajador.
2. `_calculate_day_value` (940) — valores negativos/cero; tope por evento.
3. `apply_field_attendance_to_sheet` (1456) — re-aplicación sobre sheet ya SUBMITTED.
4. `biometric/tabular_reader.py` — parser del reloj: filas corruptas, encoding, duplicados.
5. `approve_field_attendance` (1222) — SoD y estado del work day post-aprobación.

### FASE C — Módulos operativos del demo

**U16 — hr module** · `modulos/hr/` (~5.100; `views.py` 1.863)
1. `EmployeeProvisionUserView` (778)/`ResetTempPassword` (811)/`RevokeAccess` (848) — permisos;
   entrega del temp password (¿en response body?); revoke desactiva memberships además del user.
   Conecta con BUG-002.
2. Lifecycle (`suspend/reinstate/terminate/rehire` 969-1022) — transiciones inválidas; efecto sobre
   nómina en curso.
3. Contratos (1094-1367) — SoD firma; amend de contrato firmado.
4. `photo_service.py`/`EmployeePhotoView` (1516) — content-type/tamaño, path traversal.
5. `EmployeeListCreateView` (341) — **unicidad de cédula por company** (clave del cruce comisariato,
   U20); N+1 con assignments.

**U17 — compras** · `modulos/compras/` (~4.000)
1. `create_purchase_draft` con `idempotency_key` opcional — ¿key vacía = sin idempotencia?
2. `post_purchase_document` → CxP (`link_procurement_document_to_payable` 530) — doble posteo;
   recepción parcial.
3. `services_orders.py` (855) — GRN llama `post_receive` de inventarios ¿con la misma idem key en retry?
4. `void_purchase_document` — void con CxP ya pagada.
5. `views.py:36` — patrón "X-Branch-Id requerido" manual por vista: buscar la vista que lo olvidó.

**U18 — ventas** · `modulos/ventas/` (~2.860)
1. `verify_pos_override_grant` (views:113) — grant firmado por supervisor para override de precio:
   TTL, replay (¿one-time?), binding a cashier+branch+ticket.
2. `PosSaleView` llama `get_effective_permissions_for_scope` directo (103) además del `rbac_permission`
   de clase — doble fuente de verdad.
3. `_sales_error_response` (67) — mapa `SALES_*` a HTTP; el frontend recibe `{"detail": code}` crudo
   (cruzar con L4).
4. Venta a crédito → CxC — límite de crédito ¿dentro de qué lock?

**U19 — retail_pos + sync_engine (riel offline)** · `sync_engine/` (~5.330), `retail_pos/` (~2.800)
1. **Doble idempotencia:** capa 1 `AppliedCommand` por `command_id`; capa 2 key de dominio en handler
   (`handlers_pos.py:135/204`). Probar: cliente reintenta con `command_id` NUEVO pero misma operación
   → ¿capa 2 atrapa?
2. **REJECTED no reintentable:** `_reject_with_db` (701) vs `_reject_without_db` — reenvío del mismo
   `command_id` rechazado debe devolver el MISMO rechazo; verificar la clasificación por causa.
3. Cuarentena por skew (315-330) — `device.save(update_fields=["status"])` **sin lock**; POS offline
   3 días con comando viejo legítimo → cuarentena. ¿Umbral compatible con offline-first rural?
4. `SyncBatchView` AllowAny (views:512) — firma Ed25519 por comando; ¿nonce/ventana anti-replay del
   batch? ¿`last_accepted_sequence` monotónico enforced?
5. `retail_pos/services.py:256 _edge_shared_secret_b64` — default `ZWRnZS1zZWNyZXQ=` ("edge-secret")
   en `compose.yaml:74`: secreto hardcodeado de QA que **no debe llegar a prod**.
6. `run_pos_compensation_cycle` — backoff, `max_attempts`, ticket cuando se agotan (¿FAILED visible
   para el cajero?).

**U20 — comisariato + intercompany + parties** · `modulos/comisariato/` (~1.980), `intercompany/` (682), `parties/` (1.113)
1. `payroll_link.py:7-8` — **cédula como clave natural cross-company**: cédulas duplicadas/vacías/
   formato distinto entre finca y comisariato → se descuenta al empleado equivocado o a nadie.
   Verificar normalización/unicidad en `hr.Employee` y `parties.Party`.
2. `_has_active_cxc_relationship` (47) — gate `IntercompanyRelationship` CXC: dirección
   (finca↔comisariato simétrica o no).
3. `sell_on_credit` (143) vs `available_credit` (107) — chequeo de límite y doc ¿misma txn con lock
   del `CustomerCreditAccount`? Dos ventas simultáneas exceden el límite.
4. `EDITABLE_SHEET_STATUSES = {DRAFT, SUBMITTED}` — fijar deducción sobre sheet SUBMITTED: ¿re-cálculo
   posterior la pisa?

**U21 — reporting kernel** · `kernels/reporting/` (~6.100)
1. `authentication.py:18-34 _decode_payload_unverified` — peek del JWT sin verificar: que NINGÚN
   claim del peek se use antes de `AccessToken`; scope del embed token.
2. `permissions.py` propio vs `rbac_permission` — dos sistemas conviviendo.
3. `domain_adapters/*` — cada adapter filtra por company (IDOR en reportes = fuga masiva).
4. `exports.py` — CSV/Excel injection (`=SUM(...)` en nombres de clientes).
5. `materialization.py` — staleness vs draft-first (¿reporta drafts como posteados?).

### FASE D — Frontend

**U22 — frontend core: boot + stores + router** · `boot/axios.ts` (281), `stores/*`, `router/`
1. `boot/axios.ts:114` — `full.pathname.replace(/\/api\/?/, '/')` reemplaza la PRIMERA `/api` en
   cualquier posición. **Ver §9 (verificado, a confirmar contra rutas reales).**
2. `auth.refresh()` **sin single-flight** (239-253) — N requests con 401 simultáneos → N refresh
   concurrentes; con rotación, el 2.º falla → `hardClearLocal()` + logout espurio. **Sospechoso alto.**
3. Interceptor 403 (272) — `router.replace('/403')` ante CUALQUIER 403, incluido un poll en
   background → expulsa al usuario de su pantalla (regla de oro 1).
4. `CONTEXT_EXEMPT_PREFIXES` (86-97) vs backend `EXEMPT_PATH_PREFIXES` — el frontend NO exime
   `/auth/2fa/verify/`: ¿por cuál instancia axios viaja el 2FA? (`authApi` no tiene interceptor de
   contexto).
5. `router/index.ts:38-62` — riel offline-first + fix BUG-001 (**intocable**); proponer test de
   vitest que congele el contrato.
6. `localStorage 'nt_device_identity'` (188) — device_id arbitrario como header (el backend debe ser
   la defensa; verificar U2-4).

**U23 — frontend auth + org + rbac + devices** · `modules/auth/` (1.551), `modules/org/` (1.245), `modules/devices/` (616)
1. Wizard de bootstrap — manejo de error del paso 2 (holding creada, empresa falla: ¿retoma o queda
   zombi?).
2. `AppLayout.vue` + `app/nav.ts` — nav gateada por ACL: item visible sin permiso = 403 sorpresivo.
3. Select-context — usuario con 1 sola company/branch: ¿auto-selección o pantalla innecesaria?
4. `modules/devices` — enrolamiento/revocación: mensajes claros del kill-switch.
5. RBAC UI — roles con nombres técnicos crudos vs español.

**U24 — frontend hr + nomina + pagador + asistencia** · `modules/hr/` (5.601), `nomina/` (2.696), `pagador/` (2.570)
1. `SalaDePagoPage.vue` — presentación neto legal vs cobros separados: que JAMÁS muestre "neto
   descontado" (invariante 1 en pantalla).
2. `NuevoTrabajadorPage.vue` — validación de cédula (formato NI, unicidad) → alimenta U20-1.
3. Submit→approve de planilla — doble click en aprobar (¿botón se deshabilita?), loading en cómputos
   largos.
4. `modules/nomina/api.ts` (542) vs `nomina/urls.py` — drift de endpoints (L4).
5. Asistencia de campo en tablet — offline (¿usa el riel sync o requiere red?).

**U25 — frontend ventas + pos + billing** · `modules/ventas/` (3.919), `modules/pos/` (offlineQueue 398), `billing/` (1.661)
1. `offlineQueue.ts` — `MAX_ATTEMPTS 8` → FAILED: ¿el cajero VE los FAILED y puede reintentar?
   (venta fantasma = plata perdida); multi-tab (dos pestañas, misma cola), quota exceeded.
2. `idempotency_key` en `CREATE_AND_CHECKOUT` — ¿estable ante retry o se regenera (rompe capa 2 de
   U19)?
3. `CajaVentaPage.vue`/`HistorialVentasPage.vue` — 8 `catch (e)`: ¿traducen o tiran `e.message`/`SALES_*`?
4. Override de precio con grant — UX (¿modal con credenciales del supervisor? ¿rastro visible?).

**U26 — frontend inventory+procurement+payments+portfolio+accounting** · (~13.900, partir si satura)
1. `modules/accounting/api.ts` (597) — flujo draft→approve→post con SoD: ¿la UI esconde "postear" al
   mismo aprobador?
2. Arqueo (payments) — conteo por denominación: validación en vivo del cuadre antes de submit.
3. Movimientos de inventario — idempotency_key en el cliente (misma discusión que U25-2).
4. Empty states — tabla "no hay datos" cuando en realidad falló la query (distinguir vacío vs error;
   `core/composables/useListado.ts`).
5. `modules/portfolio` — aging/saldos: formato de moneda consistente NIO/USD (`core/format.ts`).

### FASE E — Verticales dormidos (última prioridad, no se borran)

**U27 — estacion_servicios + fuel (front)** · `modulos/estacion_servicios/` (~3.190), `frontend/modules/fuel/` (1.422)
Ciclo de compensación fuel (espejo del POS — mismos bugs), calibración de tanques, 7 `select_for_update`.

**U28 — finca + financiamiento + fleet + cec + beneficio** · (dormidos, pero con ganchos vivos)
`finca/accounting_link.py:96` (caller de posteo — entra en L3 aunque el módulo duerma); financiamiento
crea Credits en portfolio (cruce con U12); handlers `handlers_finca.py`/`handlers_fleet.py` registrados
en `registry.py` (superficie del batch AllowAny aunque el módulo esté apagado — ¿invocable?).

**U29 — knowledge + diagnostics + integration + soporte** · (dormidos)
`diagnostics/capture.py` (receivers de señales que corren en TODA operación — overhead/side-effects
globales); `documents` upload (checklist de U16-4); `handlers_demo.py` en sync (¿demo handler
alcanzable en prod?).

**U30 — stubs y arrastre v2** · stubs (`modulos/accounting|facturacion|inventarios` 35-43 LOC),
`modulos/sync/` (0 LOC), `certification*.py` (~2.500), `phase7/7b/8.py`, `urls_legacy.py`.
Objetivo: inventario documentado de código muerto/dormido con su riesgo (rutas montadas, señales,
imports) — NO borrar, solo mapa.

---

## 8. Lentes transversales (cruzan todo el repo)

**L1 — Seguridad / authz (IDOR + self-auth).** (a) `get_queryset`/`filter` de vistas list/detail sin
`company=request.company` (grep `objects.filter(` en views × `request.company`); (b) los **9 AllowAny
confirmados** — `accounts/views.py:367,452,798,950,972` (login/refresh/2FA-verify/bootstrap-status/init)
y `sync_engine/views.py:260,512` (enroll one-time; batch firma Ed25519) — para cada uno, el mecanismo
compensatorio documentado o hallazgo; el resto de `authentication_classes=[]` (20 archivos) son
`HealthView` triviales; (c) self-auth: firma Ed25519 del sync, HMAC del edge POS (+secreto default de
compose), grant de supervisor de ventas, embed JWT de reporting — replay/TTL/binding en los 4; (d)
serializers con `company_id`/`branch_id`/`state` escribibles; (e) `is_superuser` como bypass (BUG-002).

**L2 — Concurrencia / idempotencia.** (a) mapa `select_for_update` por app (portfolio=3 es el outlier
bajo vs payments=17 — sospechoso); (b) check-then-act sin lock (`exists()`→`create`, `available_credit`→
venta, `User.objects.exists()`→bootstrap); (c) toda idempotency_key: ¿unique constraint en DB o solo
`filter().first()`? (grep `idempotency` en models vs services); (d) orden de locks en operaciones
multi-fila (transfer inventario, allocation multi-obligación); (e) **ausencia total de `on_commit`**
(verificada): efectos externos (print jobs, outbox) dentro de txns que pueden rollbackear.

**L3 — Integridad contable.** Los 6 call sites de `link_operational_event_to_accounting` (facturacion
×2, inventarios, accounting-dispatch, nomina, finca) + **la lista inversa**: operaciones con impacto
económico que NO linkean (¿payments captura? ¿compras postea solo vía portfolio? ¿ventas POS postea
vía facturacion o directo?). Por cada camino: ¿balanceado por construcción?, ¿respeta período cerrado?,
¿try/except que traga el link? (patrón confirmado en `nomina/portfolio_link.py` — buscar gemelos), ¿`_q_money`
consistente? Draft-first: buscar `JournalEntry.objects.create` fuera de `post_journal_drafts`.

**L4 — Calidad frontend (usuario del campo).** (a) drift `modules/*/api.ts` vs `urls.py` (extraer
paths de los 24 api.ts × `grep path( */urls.py`); (b) códigos crudos al usuario (grep `detail`/
`e.message`/`error.code` en componentes; catálogo `SALES_*`/`SYNC_*`/envelope vs diccionario de
traducción — ¿existe uno central?); (c) empty state vs error state (`useListado.ts`, QTables); (d)
loading states en operaciones largas; (e) responsive tablet en las 5 pantallas del demo; (f)
doble-submit en botones de acción monetaria.

**L5 — Drift v2↔v3 y arrastre.** Con paridad byte-a-byte confirmada: (a) `diff -rq` al final de cada
tanda — todo delta ↔ un BUG-ID; (b) cruzar bugs conocidos de v2 (BUGS/docs de v2, solo lectura)
contra el código copiado: bug documentado en v2 y no arreglado = hallazgo pre-confirmado en v3; (c)
inventario U30.

---

## 9. Hallazgos preliminares (ya verificados a mano — head start)

- **`nomina/portfolio_link.py` — NO es doble-cobro silencioso (falso alarma del diseño).** El
  `_apply_to_portfolio` traga excepciones (`except (PortfolioDomainError, ValueError, RuntimeError,
  TypeError): return None`), PERO el llamador `register_payroll_loan_deduction` aplica **NM-06**:
  setea `deduction.abono_applied = applied or 0.00`, y si `abono_applied < amount_deducted` loguea
  `payroll_loan_abono_pending` (queda visible para conciliación; el empleado NO queda descontado sin
  registro). **Residual real:** no hay cola de reintento ni alerta automática → **MEJORA (media)**,
  no crítico. Documentar como mejora, no como bug de doble cobro.
- **`boot/axios.ts:114` `getPath`** — `full.pathname.replace(/\/api\/?/, '/')` reemplaza la PRIMERA
  ocurrencia de `/api` en cualquier posición del path. Verificar contra las rutas reales: si alguna
  ruta legítima contiene `api` fuera del prefijo, se normaliza mal y las exenciones de contexto/refresh
  se aplican a la ruta equivocada. Severidad a confirmar (probable bajo/medio salvo colisión real).
- **`auth.refresh()` sin single-flight (`axios.ts:239-253`)** — candidato **alto** de UX: ráfaga de
  401 concurrentes puede disparar logout espurio con rotación de refresh. Priorizar en U22.
- **Suite base backend VERDE** y los 7 kernels presentes (confirmado). El `diff -rq` v2↔v3 hoy solo
  debería mostrar `auth.store.ts` + el tooling repuesto (`qa/`, `requirements/`, configs, `.env`).

---

## 10. Estrategia de regresión (por fix y por ola)

**Baseline (ya hecho):** commit local del árbol; suite backend verde registrada.

**Por cada fix:** BUGS.md primero → test que falla antes/pasa después → fix mínimo → suite dirigida
`pytest src/apps/<...> src/tests -q` → typecheck/lint/vitest si tocó frontend → commit local atómico
con el BUG-ID (sin push).

**Por cada ola:** suite completa backend + `frontend_ci`; smoke E2E del bootstrap en DB efímera si
se rozó `stores/`/`router/`/`boot/`/`accounts/`; `diff -rq` v2↔v3 (cada delta ↔ BUG-ID cerrado; delta
sin BUG-ID = se revierte o se documenta).

---

## 11. Cuándo terminaste (criterios de cierre) + informe final

La auditoría está **completa** cuando se cumplen los tres:

1. **Cobertura:** las **30 unidades + 5 lentes** tienen un veredicto registrado en
   `docs/AUDITORIA_LOG.md` (bug encontrado / verificado-OK / mejora / decisión-de-diseño). Ninguna
   queda en "pendiente" o "en-curso".
2. **Fixes:** **todos los crítico/alto** confirmados están cerrados en `BUGS.md` con su test de
   regresión, y la **suite backend + `frontend_ci` quedan verdes**. Los medios/bajos quedan
   documentados (abiertos), no arreglados.
3. **Trazabilidad:** `diff -rq` v2↔v3 mapea **cada** archivo distinto a un BUG-ID cerrado (o al fix
   BUG-001 / al tooling repuesto). Delta sin BUG-ID = se revierte o se documenta.

**Informe final** (agregalo al pie de `AUDITORIA_LOG.md` y avisá al usuario): resumen numérico —
bugs por severidad (crítico/alto/medio/bajo), mejoras propuestas, certificados "verificado-OK", y
lista de BUG-IDs nuevos (BUG-004+) con su estado. Más un párrafo de "riesgo residual" (lo que quedó
como medio/bajo sin arreglar) para que el usuario priorice.

**Checkpoint (clave para sobrevivir resets de cuota):** actualizá `AUDITORIA_LOG.md` **después de
cada unidad**, no al final. Si la sesión se corta, la siguiente retoma leyendo el log: sigue por la
primera unidad en "pendiente".

---

*Fin del runbook. Arrancá por §0 (Primeros pasos) → ola 1 (U1-U4) en modalidad (A) inline.
Documentá cada hallazgo confirmado en `BUGS.md` (BUG-004+) **antes** de tocar código, y el veredicto
de cada unidad en `docs/AUDITORIA_LOG.md`.*
