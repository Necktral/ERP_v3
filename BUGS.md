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
