# BUGS — ERP_v3

Registro de bugs encontrados durante el testeo.

> **Regla (constitución):** el bug se **documenta ANTES de arreglarlo** — pasos para reproducir, esperado vs. actual, impacto.

## Cómo registrar un bug

Copiá la plantilla, ponela en **Bugs abiertos**, numerala (BUG-001, BUG-002, …) y completala. Al arreglarlo, movela a **Bugs cerrados** con la causa raíz y el fix.

---

## Plantilla

### BUG-000 — <título corto>

- **Módulo / paso del ROADMAP:**
- **Fecha:**
- **Severidad:** crítico / alto / medio / bajo
- **Estado:** ABIERTO / EN PROGRESO / CERRADO
- **Pasos para reproducir:**
  1.
  2.
  3.
- **Esperado:**
- **Actual:**
- **Impacto:** ¿bloquea el flujo? ¿descuadra contabilidad? ¿confunde al usuario del campo?
- **Causa raíz / fix:**

---

## Bugs abiertos

### BUG-002 — El admin del bootstrap es superusuario permanente (divergencia con la constitución)

- **Módulo / paso del ROADMAP:** 1 (estructura organizacional) / arranque
- **Fecha:** 2026-07-01
- **Severidad:** media
- **Estado:** ABIERTO
- **Pasos para reproducir:**
  1. Completar el wizard de bootstrap (crea el usuario admin inicial).
  2. Revisar el usuario creado: `is_superuser=True`, permanente.
- **Esperado:** según la constitución (§ arranque), el primer admin es **temporal** — un puente para el primer ingreso que se **desactiva/borra** una vez que el admin se registra como empleado-administrador y crea a los demás.
- **Actual:** el bootstrap crea un superusuario permanente; no existe el paso de "desactivar admin temporal".
- **Impacto:** no bloquea el paso 1, pero deja un superusuario suelto no ligado a un empleado. A revisar cuando se implemente el empleado-administrador (paso 3, HR).
- **Causa raíz / fix:** pendiente (decisión de diseño; probablemente en el paso 3).

## Bugs cerrados

### BUG-009 — Intercompañía: el frontend usaba `id` pero el backend manda `tx_id` — todas las acciones pegaban a /transactions/undefined/

- **Módulo / paso del ROADMAP:** frontend accounting (IntercompaniaPage) / hito intercompany — detectado en oleada 2 (preexistente, venía así de v2)
- **Fecha:** 2026-07-02
- **Severidad:** alta para el hito intercompany (la pantalla lista pero NINGUNA acción funciona)
- **Estado:** CERRADO
- **Pasos para reproducir:**
  1. Crear un cruce intercompañía y abrir la pantalla Intercompañía.
  2. Intentar "Confirmar" (o conciliar/liquidar/cerrar/disputar).
- **Esperado:** POST a `/accounting/intercompany/transactions/<tx_id>/confirm/` y la transición de estado.
- **Actual:** el payload del backend (`_serialize_intercompany`) trae `tx_id` (UUID) y NO `id`; el frontend leía `tx.id` (undefined) → POST a `/transactions/undefined/confirm/` → 404 siempre. Además `row-key="id"` dejaba el row-key undefined y la columna `#` en blanco. El index signature `[k: string]: unknown` del tipo escondía el error al typecheck.
- **Impacto:** el flujo intercompany por UI está muerto de punta a punta (solo listar funcionaba). No corrompe datos.
- **Causa raíz / fix:** drift de contrato api.ts ↔ payload (la lente L4 valida rutas, no shapes). **Fix:** `IntercompanyTx.tx_id: string` (sin `id` fantasma), `row-key="tx_id"`, columnas y las llamadas `intercompanyAction`/`disputeIntercompanyTx` usan `tx_id`.

### BUG-008 — Apertura de caja concurrente revienta con IntegrityError crudo (500) en vez de conflicto de dominio (409)

- **Módulo / paso del ROADMAP:** payments kernel (pasos 8-9: caja/arqueo) / unidad U10 de la auditoría — oleada 2
- **Fecha:** 2026-07-02
- **Severidad:** media (el invariante NO se viola — el constraint único lo sostiene — pero el segundo cajero ve un error 500 críptico en vez del mensaje claro de "ya hay una caja abierta")
- **Estado:** CERRADO
- **Pasos para reproducir:**
  1. Dos POST concurrentes de apertura de caja para el mismo `register_id` de la misma sucursal.
- **Esperado:** uno abre (201) y el otro recibe `PaymentsConflictError` ("Ya existe una cash session OPEN…") → 409 con mensaje en español.
- **Actual:** el chequeo `exists()` bajo `select_for_update` tiene ventana de carrera (no hay filas que lockear cuando ambos llegan a la vez); ambos pasan el chequeo y el segundo INSERT muere con `IntegrityError: uq_cash_session_open_per_register` → 500.
- **Impacto:** solo UX/robustez del error; los datos quedan bien (1 sola sesión OPEN).
- **Causa raíz / fix:** el guard de dominio confiaba en el pre-chequeo; el constraint parcial de BD es el árbitro real bajo concurrencia. **Fix:** `open_cash_session_for_scope` captura el `IntegrityError` del constraint y lo re-lanza como `PaymentsConflictError` con el mismo mensaje del pre-chequeo. **Test de regresión:** `kernels/payments/tests/test_u10_u11_concurrencia.py::test_apertura_concurrente_mismo_register_solo_una_open` (encontrado por este test: se escribió ANTES del fix y falló contra el código viejo).

### BUG-007 — La idempotencia de movimientos de inventario NO comparaba el lote (falso match silencioso)

- **Módulo / paso del ROADMAP:** inventarios kernel (paso 5) / unidad U8 de la auditoría — oleada 1
- **Fecha:** 2026-07-02
- **Severidad:** alta (integridad de inventario por lote: un reintento con lote distinto se "traga" en silencio)
- **Estado:** CERRADO
- **Pasos para reproducir:**
  1. Ítem con `track_lots=True`. `post_receive` con `idempotency_key=K` y `lot_number="L1"`.
  2. Repetir `post_receive` con el MISMO `K` pero `lot_number="L2"`.
- **Esperado:** `InventoryConflictError` ("Idempotency key reutilizada con payload distinto"), como ya pasa con warehouse/qty/costo.
- **Actual:** la segunda llamada devolvía el movimiento del lote L1 como si fuera un replay legítimo — el caller cree que recibió en L2 y el kardex por lote queda mentiroso.
- **Impacto:** cualquier caller directo que reintente con idempotency_key y lote corregido cree que aplicó el cambio y no fue así; trazabilidad de lotes (FEFO/vencimientos) comprometida. (Nota de alcance: los handlers actuales del riel sync NO propagan lote, así que hoy el riel no ejercita este camino — el fix protege a los callers directos con lote y a cualquier handler futuro que lo propague.)
- **Causa raíz / fix:** `_assert_receive_idempotency_match` / `_assert_issue_idempotency_match` (`kernels/inventarios/services.py`) validaban warehouse/item/qty/costo/source pero **no el lote**. **Fix:** ambas reciben el lote solicitado (`lot_id`/`lot_number`) y conflictúan si difiere del `existing.lot` (incluido el caso "antes con lote, ahora sin lote" y viceversa). **Test de regresión:** `kernels/inventarios/tests/test_u8_idempotencia_y_transferencias.py::test_receive_key_reusada_con_otro_lote_conflictua` (encontrado por este test: se escribió ANTES del fix y falló contra el código viejo).

### BUG-006 — Un 403 en un poll de fondo expulsaba al usuario a /403 (interceptor global sin distinción)

- **Módulo / paso del ROADMAP:** frontend core (boot/axios) / hot-spot U22-3 de la auditoría — oleada 0
- **Fecha:** 2026-07-02
- **Severidad:** media (UX: te saca de la pantalla donde estás trabajando)
- **Estado:** CERRADO
- **Pasos para reproducir:**
  1. Estar en el tablero (poll de resumen cada 60s) con una sesión cuyo permiso del resumen fue revocado (o un 403 transitorio de contexto).
  2. Esperar el siguiente tick del poll.
- **Esperado:** el poll falla en silencio (o avisa discreto); el usuario sigue donde está.
- **Actual:** el interceptor de respuesta hacía `router.replace('/403')` ante CUALQUIER 403, incluidos los de requests en segundo plano — el usuario era expulsado de su pantalla sin haber hecho nada.
- **Impacto:** no descuadra nada, pero confunde y hace perder el trabajo en curso (formularios a medio llenar).
- **Causa raíz / fix:** el interceptor no distinguía requests de usuario vs. de fondo. **Fix:** flag `background?: boolean` en la config de axios (`frontend/src/boot/axios.ts`); con `background:true` el 403 NO navega (el caller decide). El poll del tablero (`TableroPage.vue` + `getDailySummary`) marca sus requests como background. El caso `DEVICE_REVOKED` (kill-switch) queda intacto.

### BUG-005 — `allocate_payment_to_obligation` podía sobre-aplicar un pago (outstanding negativo) bajo concurrencia

- **Módulo / paso del ROADMAP:** portfolio kernel (pasos 7/9/10: CxC, pagos, cartera)
- **Fecha:** 2026-07-01
- **Severidad:** alta (integridad de dinero: descuadre de cartera, viola el invariante de saldo)
- **Estado:** CERRADO
- **Pasos para reproducir:**
  1. Una obligación (CxC) con outstanding = 100.
  2. Dos `allocate_payment_to_obligation` concurrentes, cada uno aplicando 80 (individualmente ≤ 100).
  3. Ambos pasan la validación `allocated_amount > obligation.outstanding_amount` (línea ~816), que
     lee el saldo **sin lock**. Luego cada uno toma el lock, re-lee e incrementa.
- **Esperado:** el segundo se rechaza (EXCEEDS_OUTSTANDING) — no se aplica más de lo que se debe.
- **Actual:** la validación de `outstanding` estaba **fuera** del lock y **no se repetía adentro**;
  el `select_for_update` protegía el `+=` (lost-update) pero no la sobre-aplicación. Resultado:
  `allocated_amount` supera `total_amount` → `outstanding_amount` **negativo**. No hay
  `CheckConstraint` que lo impida (solo existen `principal>0` y `allocated>=0`). Contraste:
  `apply_payroll_abono` sí lee el saldo DENTRO del lock y topa con `min()` — patrón correcto.
- **Impacto:** pago mal aplicado / cartera descuadrada de forma silenciosa (sin excepción ni
  constraint). Ventana: dos aplicaciones concurrentes a la misma obligación (p. ej. auto + manual).
- **Causa raíz / fix:** `portfolio/services.py::allocate_payment_to_obligation` ahora **re-valida
  `allocated_amount > obligation.outstanding_amount` DENTRO del `transaction.atomic()`**, después del
  `select_for_update`, y levanta `EXCEEDS_OUTSTANDING` (roll-back de la allocation). **Test de
  regresión determinístico:** `test_portfolio_services.py::test_allocate_payment_rejects_over_allocation_under_concurrent_change`
  (objeto en memoria con saldo viejo + DB avanzada → rechaza y no deja allocation huérfana). Verde.

### BUG-004 — El bootstrap inicial podía crear DOS superadmins bajo POST concurrente (race)

- **Módulo / paso del ROADMAP:** 1 (arranque) / `accounts.BootstrapInitView`
- **Fecha:** 2026-07-01
- **Severidad:** media (ventana angosta: solo en el primer arranque, antes de que exista cualquier usuario)
- **Estado:** CERRADO
- **Pasos para reproducir:**
  1. Con la DB vacía (primer arranque), enviar **dos** `POST /auth/bootstrap/init/` casi simultáneos
     con usuarios distintos.
  2. Ambos pasaban el chequeo `if User.objects.exists()` (los dos ven cero usuarios) y ambos creaban
     un `create_user(..., is_superuser=True)`.
- **Esperado:** el contrato "solo se permite cuando no hay usuarios" se respeta → **un** admin.
- **Actual:** el chequeo y el `create_user` no estaban dentro de una transacción con lock, así que dos
  requests concurrentes creaban **dos superadmins** (o un 500 por `IntegrityError` si coincidían en el
  username).
- **Impacto:** dos superusuarios no intencionados en el arranque. No bloqueaba el demo, pero violaba
  el contrato de arranque.
- **Causa raíz / fix:** faltaba serialización. **Fix:** `accounts/views.py::BootstrapInitView.post`
  ahora envuelve el chequeo+creación en `transaction.atomic()` con un `pg_advisory_xact_lock` y
  re-chequea `User.objects.exists()` **dentro** del lock (double-check + fast-path fuera del lock).
  **Test de regresión:** `src/tests/test_bootstrap_api.py::test_bootstrap_init_concurrent_creates_single_admin`
  (dos hilos con barrier; afirma un solo admin y `[201, 400]`). Verde (8/8 en el archivo).

### BUG-003 — El `qa/` de raíz de v2 no se copió a v3 (copiado incompleto)

- **Módulo / paso del ROADMAP:** tooling de QA (no bloquea ningún paso del demo)
- **Fecha:** 2026-07-01
- **Severidad:** baja
- **Estado:** CERRADO
- **Pasos para reproducir:**
  1. Correr la suite backend completa (`DJANGO_SETTINGS_MODULE=config.settings.test pytest`).
  2. Observar 6 FAILED en `src/tests/test_u5_migration_safety_guard.py` y `src/tests/test_qa_security_findings_guard.py`.
- **Esperado:** los tests de los guards de QA encuentran los scripts en `qa/` de la raíz del repo (como en v2, que tiene `qa/` en raíz **y** `backend/qa`).
- **Actual:** el copiado inicial de v3 solo trajo `backend/qa` (con `reports/`); faltaba el `qa/` de raíz con `migration_safety_guard.py`, `contracts/`, `k6/`, `manifests/`, etc. Los tests fallaban con "can't open file '/app/qa/migration_safety_guard.py'".
- **Impacto:** no afecta el ERP en runtime; deja sin red de seguridad de QA (guards de migraciones, arquitectura, seguridad) y 6 tests rojos. Mismo patrón que el `requirements/` que ya se había repuesto.
- **Causa raíz / fix:** copiado incompleto de v2 → se repuso la carpeta `qa/` completa en la raíz de v3 (72 items). Re-verificado: los 6 tests ahora pasan; la suite backend queda completamente en verde.

### BUG-001 — Al terminar el wizard, el admin rebota a /login en vez de entrar al sistema

- **Módulo / paso del ROADMAP:** 1 (estructura organizacional) / wizard de bootstrap
- **Fecha:** 2026-07-01
- **Severidad:** alta (bloquea el cierre del flujo para el usuario del campo)
- **Estado:** CERRADO
- **Pasos para reproducir:**
  1. Con la DB vacía, completar el wizard: crear admin (paso 1) → crear holding/empresa/sucursal (paso 2).
  2. En la pantalla de éxito, hacer clic en "ENTRAR AL SISTEMA".
- **Esperado:** el admin (ya autenticado) entra directo al tablero.
- **Actual:** el guard rebotaba a `/#/login`, que además mostraba el banner stale "Primer arranque: aún no hay usuarios" (cuando el admin ya existía). El usuario quedaba varado en un login confuso pese a estar logueado (`/api/auth/me/` = 200).
- **Impacto:** flujo que no cierra — un cajero del campo completaría el setup y no lograría entrar sin recargar la página a mano.
- **Causa raíz / fix:** `applyBootstrapUser` (`frontend/src/stores/auth.store.ts`) marcaba al usuario como autenticado pero no refrescaba `bootstrapState.is_fresh`; y `checkBootstrap()` cachea (`if (this.bootstrapChecked) return`), así que el guard seguía viendo `is_fresh=true` y rebotaba a /login. **Fix:** `applyBootstrapUser` ahora setea `bootstrapState = { is_fresh:false, setup_required:!is_setup_complete }` y `bootstrapChecked=true`. Verificado end-to-end: tras el fix, el admin cae directo en `/#/tablero`.
