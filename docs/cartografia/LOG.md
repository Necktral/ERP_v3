# LOG — Programa de cartografía de ERP_v3

> **Plan:** [PLAN_CARTOGRAFIA.md](PLAN_CARTOGRAFIA.md). El plan de ejecución está aprobado: Fases 0 a 4, con una parada en cada compuerta.
> **Base:** worktree `/home/wis/dev/ERP_v3_forensic`, rama `audit/cartografia-2026-10`, desde `dace480`.
> **Regla:** este LOG se actualiza al cerrar cada paso. Nada se da por cerrado porque lo diga un agente: **HECHO no es lo mismo que VERIFICADO**.

## Cómo retomar (leer primero)

- **Fase actual:** la Fase 0 está CERRADA (Compuerta 0 aprobada el 2026-10-05). **Próximo paso:**
  1. el PR de `audit/cartografia-2026-10` contra `main` (D-07);
  2. el plan de la V4 en modo plan (D-06), que aprueba Wis.
- **Los stacks aislados están desmontados.** Para volver a levantar uno: `erpbl preflight` y después `erpbl compose up -d db backend`. La imagen `erpv3-baseline/backend:545ab70dd5c6` se conserva.
- Todo docker y todo make pasan por `docs/cartografia/stack/erpbl`. **Nunca se corre `docker compose` ni `make` directo, porque resuelven al demo `erp_crm`.**
- La evidencia está en `.evidencia/`, fuera de git. La corrida activa se consulta con `erpbl run-dir`.
- Antes de seguir, `erpbl demo-fingerprint compare T0` tiene que dar "igual".

## Leyenda

| Estado | Significado |
|---|---|
| PENDIENTE | No empezó |
| EN-CURSO | En curso |
| HECHO | Terminado por quien lo hizo |
| VERIFICADO | Confirmado por alguien distinto en la compuerta |
| BLOQUEADO(motivo) | Frenado, con su motivo |
| DIFERIDO | Postergado a propósito |

## Estado actual

**Fase 0 CERRADA. Compuerta 0 aprobada el 2026-10-05.**
- **El demo está intacto:**
  - la huella docker y la del repo son iguales a T0;
  - de 14.482 eventos registrados, el único que no es ruido es el tag de imagen que hizo el propio programa en 0.1c, que no toca ni los contenedores ni el volumen.
- **La línea base de `dace480` está sellada.** El código está sano, y los rojos son de proceso (BUG-079).
- **El port de PR-9 y BUG-074 están en una rama aparte.**
  - Los 5 bugs pasaron de rojo a verde, y los auditores los aprobaron con observaciones.
  - La regresión completa da igual que la línea base, más 35 pruebas nuevas.
  - `REVISION_PR9.md` está en la rama del port.
- **Bugs nuevos del programa:** BUG-075 (crítico), BUG-076 a BUG-079 y **BUG-080 (crítico, confirmado)**.
- **Rumbo:** V4 (D-06), con el PR del programa al cerrar la F0 (D-07).
- **Pendiente de Wis:**
  - aprobar o no el port;
  - cuándo y dónde se arreglan BUG-075 y BUG-080 (en v3 o en la V4);
  - aprobar el plan de la V4;
  - la descarga de Chromium 1234, que con la V4 pierde prioridad.

## Fase 0 — Preparar el terreno

| # | Paso | Estado | Qué prueba | Evidencia | Commit | Verificó |
|---|---|---|---|---|---|---|
| 0.1a | Herramientas: `erpbl`, override, `sellar.py`, `linea_base.sh` | HECHO | Que no haya forma de apuntar al demo: preflight G1–G7 OK y 5 pruebas negativas rechazadas | `docs/cartografia/stack/` | — | — |
| 0.1b | Demo protegido: huella T0, `pg_dump` de solo lectura y vigilante | HECHO | Que el demo se puede restaurar y que cualquier evento sobre él queda registrado | `.evidencia/_demo/` | — | — |
| 0.1c | Git: `worktree repair`, rama del programa, worktree pr9 y tag de la imagen | HECHO | Que git funciona y que el código es exactamente `dace480` | `.evidencia/_programa/` | — | — |
| 0.1d | Esqueleto del LOG | HECHO | — | este archivo | — | — |
| 0.2 | Stack aislado desde una DB vacía | HECHO | Proyecto `erpv3_baseline`: 226 migraciones desde cero (0 pendientes), API 200, frontend 200 con proxy `/api` 200. El demo quedó igual a T0 | `erpbl preflight` | — | — |
| 0.3 | Línea base sobre `dace480` | HECHO, salvo Playwright | El código está sano. Los rojos son de proceso, fecha, aviso vivo, falso positivo o entorno. Sellada (124 archivos, `SHA256SUMS` OK) | `.evidencia/dace48003f5a/20261004T234709Z-baseline/` (`comparacion_agosto.md`) | `dace480` | — |
| 0.4 | Agentes ERP y su calibración | HECHO | El verificador acertó 4/4. El auditor rechazó el paquete BUG-012 de julio con los 2 defectos plantados, más una regresión grave. Están instalados en `.claude/agents/`, con Bash de solo lectura porque Glob y Grep no existen en este entorno | `.evidencia/_calibracion/RESULTADO_CALIBRACION.md` | (en 0.6) | calibración |
| 0.5 | Port de PR-9 y BUG-074 en rama aparte | HECHO | 15 commits: 8 rojos (todos fallaron donde se predijo), 6 arreglos y 1 de cobertura. **Los 5 auditores aprobaron, con observaciones**: BUG-011, 010, 013, 074 (con el mensaje 409) y 012. Regresión completa: ver la bitácora del cierre. `REVISION_PR9.md` va en la rama del port | `.evidencia/<commit>/…-rojo-*`, `…-verde-*`, `.evidencia/_auditoria/` | `640ae37`…`94a2cf5` | erp-auditor |
| 0.6 | Cierre y Compuerta 0 | VERIFICADO | El tercero confirmó 13/13. Regresión del port sellada (114 archivos), demo igual a T0, stacks desmontados y `git diff dace480..HEAD -- backend frontend` vacío en la rama del programa. C-21 se confirmó como BUG-080, con verificación independiente 6/6 | `.evidencia/_auditoria/verificacion_fase0/`, `.evidencia/94a2cf56e8a6/20261005T015935Z-regresion-final/`, `.evidencia/_auditoria/bug080/` | `f5a117e`…`2580016` y `231e376` (port) | erp-verificador-fresco |

### Números de referencia: agosto frente a lo observado

| Métrica | Agosto | Observado | Veredicto |
|---|---|---|---|
| Pruebas backend (testpaths) | 2,072, con 1 skip autorizado | **2,073**: 0 fallas, 0 errores, 1 skip (el de `sklearn`, autorizado), cobertura 88 % | Verde. El documento de agosto cuenta una prueba menos |
| Las 7 carpetas fuera de testpaths | no corrían | **203** pruebas, 0 fallas, 0 errores | Verdes, pero ningún gate las corre (C-03) |
| Migraciones desde cero | 226 | 226 al arrancar y en el ensayo; 227 en la rama del port (0022) | Igual |
| mypy | 0 errores | **2 errores** `unused type: ignore` en `parties/admin.py`, con la misma imagen | Rojo de entorno (C-13) |
| Vitest | 59/59 | 59/59, en 19 archivos | Igual |
| Playwright | 4/4 | **BLOQUEADO**: falta chromium 1234 (en caché solo está la 1243) | Pendiente de autorizar la descarga |
| route-authz (escrituras / con RBAC / excepciones) | 306/292/14 | 306/292/14 | Igual |
| L4 drift (rutas / llamadas / rotas / huérfanos) | 508/388/0/13 | 508/388/0/13 | Igual |
| OpenAPI | ≥ 851 rutas, ≤ 23 advertencias | 853 rutas, 23 líneas de advertencia | Igual |
| Preflight de producción | — | rc=0, 0 errores, 541 advertencias | Verde |
| E2E del POS (edge) | aprobado | aprobado en el reintento, con el secreto correcto | Igual |
| Guardia de cierre (informativa) | PASS | 10 observaciones, todas explicadas | Ver `comparacion_agosto.md` |

## Fase 1 — Cartografía

_(pendiente)_

## Fase 2 — Documentación

_(pendiente)_

## Fase 3 — Caza de bugs

_(pendiente)_

## Fase 4 — Fortalecimiento

_(pendiente)_

## Decisiones humanas (D-IDs)

| ID | Pregunta | Opciones | Decisión | Fecha | Fuente |
|---|---|---|---|---|---|
| D-01 | ¿Qué se hace en la Fase 0 con BUG-010 a 013 y el caso de "Aplicar asistencia"? | Integrarlos · Solo documentarlos · Prepararlos aparte para revisión | **Se preparan en una rama aparte y Wis los revisa antes de que entren** | 2026-10-04 | chat |
| D-02 | Orden por capas | — | **El frontend va al final** en la caza y en los arreglos. El mapa se hace vertical. Los bugs de frontend que tocan plata o bloquean una operación se tratan como de negocio | 2026-10-04 | chat |
| D-03 | Base del programa | — | Worktree forense, rama `audit/cartografia-2026-10` desde `dace480` | 2026-10-04 | plan aprobado |
| D-04 | Respaldo del demo | — | Sí, un `pg_dump` de solo lectura (único contacto con el demo) | 2026-10-04 | plan aprobado |
| D-06 | ¿Cómo sigue el programa? | Terminar la v3 · Reescribir la V4 desde cero · V4 copiando v3 módulo por módulo | **V4 copiando v3 módulo por módulo, con compuerta por módulo.** La F1 y la F2 se hacen al integrar cada módulo. Antes: un mapa global liviano y el esqueleto con contrato de módulo (PLAN §0) | 2026-10-05 | chat |
| D-07 | ¿Se publica el programa en GitHub? | Seguir sin GitHub (D-05) · PR ya · PR al cerrar la F0 | **PR de `audit/cartografia-2026-10` contra `main` al cerrar la Fase 0.** Lleva los 93 commits que main no tiene, entre ellos la auditoría de agosto y los arreglos de integridad, que solo existían en local. **Reemplaza a D-05 solo para este PR.** El port (`fix/pr9-copa-nomina-port`) no va | 2026-10-05 | chat (botón Create PR + pregunta) |
| D-05 | ¿Se usa GitHub? | — | **No.** Wis no tiene acceso a la cuenta y no lo va a tener. Por lo tanto: sin push, sin PR y sin fetch. Las ramas se integran con merges locales y la publicación queda fuera del programa. Las guardias que comparan contra `origin/main` usan la copia local, del 2026-08-18 | 2026-10-04 | chat |

## Candidatos a bug (C-IDs; se numeran como BUG cuando se confirman)

| ID | Candidato | Estado |
|---|---|---|
| C-01 → BUG-077 | `qa/run_qa_ci.sh:85` llama a `python`, pero el host solo tiene `python3`. Si el manifest no se escribe, el runner igual imprime PASSED (`set -uo pipefail` sin `-e`) | A confirmar en 0.3 |
| C-02 → BUG-076 | `docker compose` y `make qa-*` sin proyecto apuntan al demo `erp_crm`. **Confirmado:** `docker compose config` desde el worktree resuelve a `erp_crm`. `qa-ci-up` con `QA_FRESH_DB=1` borra su volumen, y `docker-clean` borra contenedores por imagen | Confirmado (0.1) |
| C-03 → BUG-078 | `backend/pytest.ini` deja afuera 7 carpetas de pruebas (23 archivos) | A medir en 0.3 |
| C-04 → BUG-079 | Tres excepciones de seguridad vencieron el 2026-09-14. Como el Gate 1 es una cadena `&&`, la falla esconde todos los pasos posteriores | Confirmado (0.3): 3 vencidas. En la corrida canónica el corte llegó antes, en C-10 |
| C-05 → BUG-079 | El cierre no es reproducible: nada produce `production_preflight.json` ni `frontend_vitest.xml`, y el manifest no guarda el commit | A confirmar en 0.3 |
| C-06 | Pagador: un comando que queda en PROCESSING no se recupera después de un crash (`queue.ts:105,187`) | Para la Fase 3 |
| C-07 | Pagador: un comando FAILED se reintenta en cada drenado, contra lo que dice `classifyError` (`queue.ts:101`) | Para la Fase 3 |
| C-08 | Pagador: un comando con `company_id` falso cae en la empresa activa | Para la Fase 3 |
| C-09 | Puede haber una planilla APROBADA dentro de un período no aprobado: `approve_period` no mira el estado de las planillas | Para la Fase 3 |
| C-10 → BUG-079 | `qa-pr-blast-radius-guard` falla sobre la rama integrada ("high/extreme blast radius requires ADR or design note in docs/adr\|docs/design"). El diff contra el `origin/main` local es enorme porque las ramas nunca se integraron (D-05). Es el **primer** paso que corta la corrida canónica | Confirmado (0.3); falta clasificar |
| C-11 → BUG-079 | `qa-static-scan` falla por 6 **falsos positivos**: el patrón `(TODO\|FIXME\|…)` atrapa las palabras "TODO" y "TODOS" de comentarios en español. **El `qa/reports/static_scan.txt` versionado el 2026-08-18 ya mostraba los mismos 6 hallazgos**, así que el "Gate 1 aprobado" de agosto no se sostiene con su propia evidencia | Confirmado (0.3) |
| C-13 → BUG-079 | `qa-backend-mypy` da 2 errores `unused type: ignore` (`parties/admin.py:45,54`) con la misma imagen con la que agosto informó 0. `requirements/dev.txt` no fija mypy ni los stubs. En la rama del port aparece igual (no lo introduce el port) | Confirmado (0.3) |
| C-14 → BUG-079 | El E2E del POS lee el secreto de `POS_EDGE_E2E_SECRET_B64` o del `.env` (si no, usa uno por defecto) y no de `POS_EDGE_CONNECTOR_SHARED_SECRET`, que es la variable del backend: el par de variables es fácil de desalinear | Confirmado (0.3) |
| C-15 | Sync: un pago replicado que choca con la clave de BUG-010 sale como `SYNC_INTERNAL_ERROR`, un motivo genérico en vez de uno de contrato, y no hay prueba de ese caso (auditoría de BUG-010) | Para la Fase 4 |
| C-16 | `payroll_payments.py:78` guarda `reference` sin `strip()`, pero la deduplicación compara con `strip()`. Con el constraint de BUG-010, una llamada directa con espacios daría 500. Hoy nadie la llama así | Para la Fase 4 (recomendación en `REVISION_PR9.md`) |
| **C-17 → BUG-075** | **CRÍTICO. Falla de seguridad en el sync.** El detalle queda reservado hasta el arreglo, en la evidencia local | **Confirmado (0.5).** Se registró como BUG en 0.6 |
| C-18 | Frontend: un `ConflictError` genérico se muestra como "CONFLICT" en toda la app. En nómina además: "Agregar trabajador" muestra el JSON crudo, "Asistencia y alimentos" muestra un mensaje genérico, y hay botones visibles que llevan a un 409 seguro | Para la fase de frontend (D-02) |
| C-19 | Sala de pago: en una empresa sin períodos, los pendientes de otra empresa no se ven ni se drenan solos | Fase 3/4 (UX) |
| C-20 | `ApiErrorEnvelopeMiddleware` no envuelve en el cable las respuestas de DRF ya renderizadas (reescribe `r.data`, pero `render()` no hace nada). Hay pruebas de todo el repo que leen `r.data` y pueden estar verificando envelopes que el navegador nunca recibe | Fase 3 (BE), prioridad media |
| **C-21 → BUG-080** | **Invariante 1:** el CO-PA calcula el neto sin `alimentacion_amount` (`comisariato/pay_negotiated.py:147,158` frente a `nomina/models.py:815`). La Sala muestra el "Neto legal" con la misma omisión (`SalaDePagoPage.vue:783`) | **Confirmado (0.6): 3/3 rojas como se predijo, −500 exactos.** Crítico. `.evidencia/dace48003f5a/20261005T023040Z-confirmacion-c21/` |
| C-22 | El CO-PA aplica cobros sin mirar el estado del período cuando los abonos consumen todo el neto (con neto 0 no se registra pago y la revisión del período no corre) | A confirmar |
| C-12 → BUG-079 | `qa-security-findings-enforce` (después de `qa-security-audits`): avisos npm altos sin resolver (brace-expansion, braces, browserslist, fast-glob, micromatch). Son avisos vivos y algunos los cubrían las excepciones vencidas | Confirmado (0.3) |

## Certificaciones VERIFICADO-OK

| Hot-spot | Mitigación (archivo:línea) | Lote |
|---|---|---|
| `SyncBatchView` usa `AllowAny` | Autentica al dispositivo con firma HMAC o Ed25519, ventana de tiempo, nonce y estado del dispositivo (`sync_engine/views.py:562-734,758-823`). No es un endpoint abierto | Fase 0, verificación V6 |

## Incidentes

_(ninguno)_

## Bitácora (solo se agrega)

- **2026-10-04 · 0.1 · Demo protegido.**
  - Se tomó la huella T0 del demo; la imagen y el volumen siguen siendo los de julio.
  - Se hizo el `pg_dump` de solo lectura: 1,5 MB, 239 tablas con datos, y `pg_restore --list` lo lee bien.
  - Quedó activo el vigilante `docker events` del proyecto `erp_crm`.
- **2026-10-04 · 0.1 · Git.**
  - `git worktree repair` del forense, con respaldo del `.git` de WSL en `.evidencia/_programa/`. Ya no figura como *prunable*.
  - Rama `audit/cartografia-2026-10` desde `dace480`.
  - Worktree `/home/wis/dev/ERP_v3_pr9` en `fix/pr9-copa-nomina-port`.
  - Tag `erpv3-baseline/backend:545ab70dd5c6`.
- **2026-10-04 · 0.1 · Envoltorio `erpbl`.**
  - El preflight dio OK.
  - Las pruebas negativas se rechazaron todas: `down -v`, `-p erp_crm`, `docker-clean`, `QA_FRESH_DB=1` y `reset-db erp_crm`.
  - Se confirmó C-02: `docker compose config` desde el worktree, sin el envoltorio, resuelve a `erp_crm`.
- **2026-10-04 · 0.2 · Stack aislado.** `erpv3_baseline` arriba en 127.0.0.1:18080/13000: 226 migraciones desde cero, API y frontend responden.
- **2026-10-04 · 0.3 · Vigilante del demo.** Registró 682 eventos en 13 minutos: todos chequeos de salud (`pg_isready` y curl de bootstrap) más la etiqueta de imagen que puse en 0.1. Cero actividad real. Se agregó `erpbl demo-eventos`, que separa el ruido.
- **2026-10-04 · 0.3 · Línea base: suite backend completa.** 2,073 pruebas, 0 fallas, 0 errores, 1 skip autorizado. Frontend CI (lint, typecheck, Vitest y build) en verde.
- **2026-10-04 · 0.4 · Calibración de agentes.**
  - El verificador acertó 4/4.
  - El auditor rechazó el paquete BUG-012 de julio y detectó los 2 defectos plantados, más una regresión grave: sin sucursal activa se perderían todos los pagos de la Sala.
  - Las definiciones ahora usan Bash de solo lectura, porque Glob y Grep no existen en este entorno.
- **2026-10-04 · 0.5 · BUG-011.** R `640ae37`: fallaron exactamente las 4 pruebas predichas. F `5e9f696`: 7/7 verdes. Diferencia justificada con PR-9: la reversa de un abono no se restringe por la relación vigente.
- **2026-10-04 · Lección.** No hay que editar `erpbl` ni `linea_base.sh` mientras corre la línea base, porque bash lee el script a medida que lo ejecuta. Esta vez no hubo daño: se revisaron los logs de los pasos de ese momento.
- **2026-10-05 · 0.3 · Línea base cerrada (salvo Playwright).**
  - 54 pasos, 9 rojos, todos clasificados.
  - Reintentos en verde: E2E del POS (el secreto lo leía de otra variable, C-14) y preflight de producción (`preflight_prod.py`).
  - Reportes movidos a la evidencia. El árbol quedó limpio y no hizo falta restaurar ningún archivo versionado: el `static_scan.txt` salió igual al de agosto.
  - Guardia de cierre informativa: 10 observaciones explicadas. Sellado y `sha256sum -c` OK.
- **2026-10-05 · 0.5 · BUG-011.** El auditor la aprobó con observaciones (`.evidencia/_auditoria/bug011/VEREDICTO.md`).
- **2026-10-05 · 0.5 · BUG-010.**
  - R `acb6e9e`: falló la prueba predicha.
  - F `5cf0a41`: migración `0022` sobre `0021`, una sola hoja, entrada manual en el baseline de migraciones.
  - 905 pruebas verdes. El ensayo aplicó 227 migraciones desde cero.
  - En auditoría.
- **2026-10-05 · 0.5 · BUG-013.**
  - R `9b6039a`: 2 rojas y 1 verde, como se predijo.
  - F `c1a76eb`: compuerta única `assert_sheet_recomputable`, conectada a "Calcular".
  - En verificación.
- **2026-10-05 · 0.5 · Auditorías.** BUG-010 aprobado con observaciones (`.evidencia/_auditoria/bug010/VEREDICTO.md`); salen los candidatos C-15, C-16 y C-17.
- **2026-10-05 · C-17 confirmado** (crítico, sync), en la base aislada `erpv3_baseline`.
  - El detalle queda reservado hasta el arreglo, en la evidencia local.
  - Se limpió lo creado en la prueba y el demo no se tocó.
  - Por la severidad se propone tratarlo antes de la Fase 1.
- **2026-10-05 · 0.5 · BUG-074.**
  - R1 `138a26f`: 6 rojas y 2 verdes, como se predijo.
  - R2 `a59efed`: la baja de línea, roja.
  - F `92e23f6`: la compuerta en asistencia de campo, INSS y alta, edición, baja y marcas de línea; 12/12 verdes.
  - En verificación.
- **2026-10-05 · 0.5 · Port completo** (`fix/pr9-copa-nomina-port`, 15 commits).
  - BUG-013 y BUG-074: compuerta única `assert_sheet_recomputable`, con 7 caminos cubiertos.
  - **Mensaje 409:** la auditoría de BUG-013 detectó que el frontend mostraría "CONFLICT". Se agregó `RecalculoBloqueadoError` más el decorador `conflicto_en_espanol`, y las pruebas miran el cuerpo que llega al navegador.
    - Se confirmó que `ApiErrorEnvelopeMiddleware` reescribe `r.data` en memoria, pero no el contenido ya renderizado.
  - **BUG-012:** port corregido según la calibración (chequeo truthy, `background`, sin dedupe por empresa ni contadores separados). CI del frontend: 64/64, lint, typecheck y build OK.
- **2026-10-05 · 0.5 · Desvío menor.** La prueba de cobertura de BUG-010 (`94a2cf5`) se commiteó segundos antes de correrla, por un error de ruta. Al correrla después dio 3/3 verde.
- **2026-10-05 · 0.6 · Plan y BUGS.**
  - `PLAN_CARTOGRAFIA.md` corregido en §2.1, §2.2, §2.3, §2.4, §3, §4, §12 y §13.
  - `BUGS.md` del programa: BUG-075 (crítico, sync), BUG-076 (QA apunta al demo), BUG-077 (falso PASSED), BUG-078 (7 carpetas fuera del gate) y BUG-079 (gates rojos por proceso).
  - Nota de numeración actualizada.
- **2026-10-05 · 0.6 · Verificación de un tercero:** 13/13 afirmaciones del informe CONFIRMADAS (`.evidencia/_auditoria/verificacion_fase0/VEREDICTOS.md`). Como dato nuevo, los reportes versionados en `qa/reports/` (por ejemplo `run_manifest.json` y `security_exceptions_guard.json`) son de mayo y dicen "passed". Eso va a la Fase 2.
- **2026-10-05 · 0.5 · BUG-012:** el auditor lo aprobó con observaciones (`.evidencia/_auditoria/bug012/VEREDICTO.md`). Sale el candidato **C-19**: en una empresa sin períodos, los pendientes de otra empresa no se ven ni se drenan solos.
- **2026-10-05 · Decisión en curso:** Wis evalúa reconstruir como V4 en `/home/wis/dev/ERP_V4`. Mi recomendación es decidirlo con el mapa al cierre de la Fase 2 y preferir una evolución que conserve los kernels. Pendiente de su respuesta.
- **2026-10-05 · 0.5 · BUG-074 y el mensaje 409:** el auditor los aprobó con observaciones (`.evidencia/_auditoria/bug074/VEREDICTO.md`). **Los 5 bugs del port quedan auditados.** Del port salen los candidatos C-18 y C-20, y de la lectura lateral C-21 (posible violación del neto legal en el CO-PA con alimentación) y C-22.
- **2026-10-05 · Rumbo propuesto por Wis:** V4 armada copiando v3 módulo por módulo. La F1 y la F2 se hacen al integrar cada módulo. Respondí que sí, con condiciones: un módulo por vez con compuerta, primero el port y la decisión sobre BUG-075, un mapa global liviano, y un esqueleto con contrato de módulo. Falta su confirmación.
- **2026-10-05 · Rumbo V4, confirmado (D-06):** Wis respondió "si terminemos la f0" a la propuesta. Quedó como D-06 y como PLAN §0.
- **2026-10-05 · Rumbo V4, precisado por Wis:** "crear paso a paso la nueva V4, un ERP modular, seguro (sin complicaciones innecesarias), con pruebas en tiempo real para ir arreglando y mapeando a la vez". Después, al ver C-21: "por eso es mejor reconstruir desde 0".
  - **Mi propuesta: desde cero en la base y no en las reglas.**
    - El esqueleto es nuevo: contrato de módulo, seguridad cerrada por defecto, pruebas en modo watch y compuerta por módulo.
    - Los cálculos legales y contables se traen de v3 uno por uno, **cada uno en un solo lugar y con su prueba**.
    - Las reglas duplicadas, como la del neto de C-21, se unifican al traerlas.
  - **Se define en el plan de la V4,** en modo plan, al cerrar la Fase 0; lo aprueba Wis.
- **2026-10-05 · 0.6 · C-21 confirmado → BUG-080 (crítico).** Prueba scratch fuera del árbol sobre `dace480`, en el stack aislado.
  - Las 3 pruebas fallaron como se predijo: el CO-PA entrega el neto **sin la alimentación**, −500 exactos en los tres casos, incluido el neto de `compute_all`.
  - La Sala muestra el "Neto legal" con la misma omisión, así que en pantalla no se nota.
  - La regla del neto vive en al menos tres lugares. Esto es un insumo directo para la V4: **una regla, un lugar, una prueba de invariante**.
  - Registrado en `BUGS.md` como ABIERTO. El arreglo queda para decidir: en v3 (rama aparte) o al integrar nómina en la V4.
- **2026-10-05 · 0.6 · Regresión final del port** (`94a2cf5`, `linea_base.sh --sin-e2e`, sellada):
  - Los resultados por paso son **idénticos a la línea base**.
  - **Pruebas:** backend 2102 en verde (+30), frontend 64 (+5) y 203 fuera del gate. Cero pruebas perdidas y cero cambios de resultado.
  - **`g2-46` (E2E del edge) pasa al primer intento,** porque `erpbl` ya exporta el secreto con el nombre correcto (C-14).
  - El preflight de producción volvió a necesitar el reintento con `preflight_prod.py`.
  - El backend tardó 67 minutos, contra 19 en la línea base, por carga concurrente en la máquina.
- **2026-10-05 · 0.6 · `REVISION_PR9.md` y las precisiones de BUG-012** se commitearon en la rama del port (`231e376`), solo documentación.
- **2026-10-05 · 0.6 · Desmontaje.**
  - Se borraron `erpv3_baseline` y `erpv3_pr9` con sus volúmenes, por `erpbl reset-db`.
  - Se limpiaron los caches root de pytest en el árbol del port.
  - **Huella final del demo:** docker igual a T0 y repo igual a T0.
  - Se detuvo el vigilante. De 14.482 eventos, el único que no es ruido es el tag de imagen de 0.1c, ya explicado.
- **2026-10-05 · D-07:** Wis pidió el PR con el botón Create PR. Le advertí que contradice D-05 y que lleva 93 commits que `main` no tiene. Eligió hacerlo **al cerrar la F0**.
- **2026-10-05 · Compuerta 0 APROBADA.** Fase 0 cerrada.
- **2026-10-05 · D-07 · Publicación.** El repo de GitHub es **público**, así que, a pedido de Wis, **el detalle de BUG-075 no se publica hasta que haya arreglo.**
  - BUGS.md, el LOG y el PLAN quedan con una línea neutra.
  - Los commits del programa, que nunca se habían publicado, se rehicieron.
  - El detalle completo y la historia original quedan en `.evidencia/_reservado/` (`BUG-075.md` y `cartografia_f0_original.bundle`).
