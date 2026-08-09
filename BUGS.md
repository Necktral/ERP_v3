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

### BUG-044 — Respuestas tardías mezclan la selección activa con el detalle anterior

- **Módulo / paso del ROADMAP:** frontend inventario/accounting/nómina / concurrencia UI
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** ABIERTO
- **Pasos para reproducir:** hacer lenta la consulta de detalle A y rápida la de B; seleccionar A y enseguida B en Listas de precios.
- **Esperado:** sólo la respuesta de la selección vigente puede actualizar el detalle y sus acciones.
- **Actual:** cada promesa escribe al resolver; A tardía reemplaza el detalle aunque B siga resaltada.
- **Impacto:** el operador puede editar o eliminar tramos/asignaciones de una lista distinta a la que cree activa; patrón candidato también en Presupuestos y Complemento.
- **Causa raíz / fix:** pendiente; aplicar latest-selection-wins mediante secuencia/abort y regresiones de respuestas fuera de orden en cada patrón confirmado.

### BUG-043 — Administración de dispositivos oculta silenciosamente los registros 201+

- **Módulo / paso del ROADMAP:** frontend devices / U23 y paginación
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** ABIERTO
- **Pasos para reproducir:** crear 201 o más dispositivos en un tenant y abrir Administración → Dispositivos.
- **Esperado:** paginación server-side con total, o carga exhaustiva explícita y acotada.
- **Actual:** la API solicita una única página `limit=200, offset=0`; la tabla descarta `count/next` y no avisa el truncamiento.
- **Impacto:** dispositivos quedan invisibles para auditoría y revocación, con riesgo operativo y de seguridad.
- **Causa raíz / fix:** pendiente; adoptar contrato paginado y cubrir navegación más allá de 200 filas.

### BUG-042 — Diálogos críticos desbordan el viewport móvil de 360 px

- **Módulo / paso del ROADMAP:** frontend inventario/nómina / responsive U24–U26
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** ABIERTO
- **Pasos para reproducir:** a 360 px abrir Agregar tramo/Asignar en Lista de precios o Historial en Régimen INSS.
- **Esperado:** diálogo y acciones completos, alcanzables sin scroll horizontal.
- **Actual:** cards fuerzan `min-width` de 380/420 px (o 360 sin margen), cortando contenido y controles.
- **Impacto:** flujos críticos de inventario y nómina quedan parcialmente inutilizables en móvil.
- **Causa raíz / fix:** pendiente; sustituir mínimos rígidos por ancho acotado al viewport y agregar regresión responsive.

### BUG-041 — Controles de sólo icono no exponen un nombre accesible

- **Módulo / paso del ROADMAP:** frontend transversal / accesibilidad U23–U26
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** ABIERTO
- **Pasos para reproducir:** navegar con lector/árbol de accesibilidad a botones papelera/copiar/cerrar en Pedidos, Biometría, Perfil de trabajador y pantallas equivalentes.
- **Esperado:** cada control expone un nombre específico y ayuda visible al foco/hover.
- **Actual:** al menos 26 botones `round icon` carecen de `label`/`aria-label`; el icono decorativo no comunica propósito fiable.
- **Impacto:** acciones, incluso destructivas, son indistinguibles mediante lector de pantalla o control por voz (WCAG 4.1.2/2.4.6).
- **Causa raíz / fix:** pendiente; etiquetar todo el conjunto U23–U26 y añadir un guard/test que evite regresión.

### BUG-040 — Una factura emitida puede perder su CxC sin consumidor durable ni reconciliador

- **Módulo / paso del ROADMAP:** facturación/portfolio/integration / recuperación cross-kernel
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** ABIERTO
- **Pasos para reproducir:** inyectar un fallo en `link_billing_document_to_receivable` durante emisión; ejecutar después el dispatcher contable y volver a emitir.
- **Esperado:** cada consumidor confirma su consecuencia de forma durable o un reconciliador idempotente crea la CxC faltante.
- **Actual:** la factura queda `ISSUED`, el evento compartido termina `SENT` tras el consumo contable, existen cero CxC y `reissue` retorna `already_issued` sin reparar.
- **Impacto:** venta válida omitida de cartera, aging y cobranza; subledger divergente del documento fiscal.
- **Causa raíz / fix:** una excepción de portfolio sólo se registra y el estado único del Outbox no representa múltiples consumidores. Pendiente: consecuencia durable por consumidor y operación de reconciliación/replay idempotente, auditable y scopeada.

### BUG-039 — Eventos contables FAILED de nómina no pueden reencolarse y el replay miente

- **Módulo / paso del ROADMAP:** nómina/accounting/integration / recuperación cross-kernel
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** ABIERTO
- **Pasos para reproducir:** aprobar nómina con fallo contable, agotar `max_attempts` del Outbox, restaurar la dependencia y reintentar por dispatcher y dominio.
- **Esperado:** una operación administrativa RBAC+audit permite reencolar; el replay es idempotente y devuelve el draft real o un estado pendiente/fallido veraz.
- **Actual:** el dispatcher sólo toma `PENDING`; `FAILED` queda terminal y el replay devuelve `ALREADY_POSTED` con `draft_id=None` por la mera existencia del evento.
- **Impacto:** planilla aprobada sin asiento y sin reparación soportada; el cierre contable queda bloqueado.
- **Causa raíz / fix:** la idempotencia confunde “evento existe” con “consecuencia completada” y no existe transición auditada `FAILED→PENDING`. Pendiente: requeue scopeado y replay basado en resultado persistido.

### BUG-038 — El lockfile frontend contiene dependencias con avisos HIGH/CRITICAL corregibles

- **Módulo / paso del ROADMAP:** frontend/supply chain / baseline QA
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** ejecutar `npm audit --json` sobre el lockfile reconstruido y confirmar el árbol con `npm ls`.
- **Esperado:** cero vulnerabilidades HIGH/CRITICAL corregibles en dependencias runtime o toolchain de entrega; cualquier residual debe tener alcance y excepción fechada.
- **Actual:** 10 paquetes reportados (3 low, 1 moderate, 5 high y 1 critical), incluidos Axios directo y `tar` transitivo de Capacitor CLI; npm indica corrección disponible.
- **Impacto:** exposición a DoS/prototype pollution y riesgo de archivos maliciosos en tooling; el alcance varía entre navegador, build y CLI.
- **Causa raíz / fix:** lockfile desactualizado y transitivas sin mínimos seguros. **Fix:** Axios/Quasar compatibles actualizados y overrides explícitos para tar, brace-expansion, postcss, immutable, nanoid y body-parser. Auditoría productiva y Capacitor quedan en cero; sólo persisten dos avisos LOW duplicados de `esbuild` en el servidor de desarrollo Windows, cuya corrección exige major de app-vite. `npm ci`, 37 tests, lint, typecheck, SPA build y `cap sync` verdes.

### BUG-037 — El importador biométrico XLSX no limita tamaño, expansión ni filas

- **Módulo / paso del ROADMAP:** nómina/biometría / plataforma y uploads
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** ABIERTO
- **Pasos para reproducir:** enviar al endpoint de importación un XLSX comprimido grande, con alta razón de expansión ZIP o con un número masivo de filas/celdas.
- **Esperado:** rechazo temprano y controlado por límites explícitos de bytes comprimidos/descomprimidos, miembros ZIP, filas y celdas.
- **Actual:** el endpoint ejecuta `upload.read()` completo y el lector descomprime/materializa el libro sin presupuestos de recursos.
- **Impacto:** un usuario autorizado puede agotar RAM/CPU del worker y degradar o derribar el servicio.
- **Causa raíz / fix:** pendiente; validar tamaño antes de leer, inspeccionar de forma segura el contenedor ZIP y aplicar límites durante el parseo con pruebas de archivos adversariales pequeños.

### BUG-036 — El secreto de dispositivos biométricos se persiste en texto claro

- **Módulo / paso del ROADMAP:** nómina/biometría / credenciales de dispositivos
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** ABIERTO
- **Pasos para reproducir:** enrolar un dispositivo y consultar directamente la columna `BiometricDevice.api_token` en la DB o un backup.
- **Esperado:** persistir sólo un hash no reversible; revelar el secreto una única vez al crear o rotar y autenticar por comparación segura.
- **Actual:** el token completo se guarda como valor `unique` y el endpoint público hace lookup directo por ese valor.
- **Impacto:** una lectura de DB/backup permite suplantar todos los dispositivos cuyos tokens sean extraídos.
- **Causa raíz / fix:** pendiente; migrar a hash versionado, agregar creación/rotación con revelación única y mantener una transición compatible y auditable.

### BUG-035 — Reanudar una venta en espera pierde identidad y crédito del cliente

- **Módulo / paso del ROADMAP:** frontend POS / Paso 7
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** CERRADO
- **Pasos para reproducir:** preparar venta para cliente con crédito, dejarla en espera, operar otro cliente y reanudar la primera.
- **Esperado:** restaurar nombre/ID, reconsultar la cuenta y habilitar crédito según el estado vigente.
- **Actual:** sólo se restaura `clienteId`; `cuenta` queda nula y `clienteNombre` puede conservar un valor stale.
- **Impacto:** deshabilita crédito legítimo y puede mostrar/imprimir la identidad equivocada.
- **Causa raíz / fix:** el ticket retenido persistía sólo el ID y el vaciado no limpiaba toda la identidad. **Fix:** conserva la identidad mínima, limpia ID/nombre/cuenta al vaciar y reconsulta el crédito vigente al reanudar, con estados explícitos de carga/error y regresiones.

### BUG-033 — Errores al consultar crédito se interpretan como “cliente sin cuenta”

- **Módulo / paso del ROADMAP:** frontend ventas/POS / Paso 7
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** CERRADO
- **Pasos para reproducir:** seleccionar un cliente con crédito y hacer que `/sales/credit-account/<id>/` responda 401/403/500, timeout o error de red.
- **Esperado:** sólo 404 significa que no existe cuenta; los demás errores se muestran y preservan un estado explícito.
- **Actual:** un `catch` general devuelve `null` para cualquier fallo y la caja continúa como si el cliente no tuviera crédito.
- **Impacto:** el cajero toma una decisión comercial incorrecta y puede negar crédito disponible sin saber que falló el sistema.
- **Causa raíz / fix:** el helper ocultaba toda excepción. **Fix:** sólo 404 devuelve `null`; autorización, servidor y red se propagan, normalizan y muestran sin sustituirlos por un estado comercial falso.

### BUG-032 — Reusar una clave de cobro con payload distinto se acepta como replay

- **Módulo / paso del ROADMAP:** facturación / idempotencia de dinero
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** cobrar con clave K y luego repetir K cambiando monto, moneda, método o documento.
- **Esperado:** conflicto de idempotencia; una clave sólo puede representar un payload canónico.
- **Actual:** el servicio devuelve el pago previo apenas encuentra K, sin comparar el payload solicitado.
- **Impacto:** el cliente puede creer que aplicó un cobro corregido cuando en realidad se conservó otro monto/método.
- **Causa raíz / fix:** el fast-path comparaba sólo la clave. **Fix:** clave única por empresa, advisory lock por empresa+clave y comparación del payload canónico completo; cualquier divergencia devuelve 409.

### BUG-031 — Completar 2FA o cambio obligatorio navega a `/dashboard` inexistente

- **Módulo / paso del ROADMAP:** frontend auth/router / transversal
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** completar correctamente 2FA con contexto activo, o guardar el cambio obligatorio de contraseña.
- **Esperado:** continuar por la entrada canónica `/`, que resuelve el destino según contexto y shell.
- **Actual:** ambas pantallas navegan a `/dashboard`, pero el router sólo registra `/tablero`; el usuario termina en 404 después de autenticarse.
- **Impacto:** bloquea el cierre normal de dos carriles críticos de acceso sin corromper datos.
- **Causa raíz / fix:** quedaron dos destinos legacy fuera del contrato del router. **Fix:** navegación canónica compartida hacia `/`, con pruebas para 2FA y cambio obligatorio.

### BUG-034 — El plan de cuentas permite ciclos entre cuentas padre

- **Módulo / paso del ROADMAP:** accounting / Paso 2
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** CERRADO
- **Pasos para reproducir:** crear A con padre B y B con padre A mediante el upsert de CoA.
- **Esperado:** la jerarquía debe ser un grafo acíclico.
- **Actual:** sólo se rechaza que una cuenta sea su propio padre; los ciclos de dos o más nodos se guardan.
- **Impacto:** recorridos, reportes y cierres que consuman la jerarquía pueden entrar en ciclos o producir agregados inválidos.
- **Causa raíz / fix:** sólo existía el guard de autorreferencia. **Fix:** mutex por empresa, lock de cuentas y validación DFS dentro de la transacción. La prueba concurrente certifica un ganador, un rechazo y cero ciclos.

### BUG-030 — El canje concurrente de un token embebido puede emitir dos tokens

- **Módulo / paso del ROADMAP:** dashboard/reporting / seguridad
- **Fecha:** 2026-08-08
- **Severidad:** media
- **Estado:** CERRADO
- **Pasos para reproducir:** canjear simultáneamente el mismo grant en estado `ISSUED` desde dos conexiones.
- **Esperado:** exactamente un canje exitoso y una sola transición a `REDEEMED`.
- **Actual:** la verificación y transición no tienen lock/CAS; ambas solicitudes pueden emitir credenciales.
- **Impacto:** replay de una capability de reporting.
- **Causa raíz / fix:** verificación y transición separadas. **Fix:** transacción y `select_for_update(of=("self",))`; la prueba concurrente deja un éxito, un conflicto y un grant `REDEEMED`.

### BUG-029 — Bootstrap organizacional concurrente puede crear dos árboles

- **Módulo / paso del ROADMAP:** accounts/iam / bootstrap
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** enviar dos `POST` simultáneos al bootstrap organizacional antes de que exista un holding.
- **Esperado:** un solo holding/empresa/sucursal; la segunda solicitud recibe conflicto controlado.
- **Actual:** el chequeo de holding ocurre antes del bloque atómico y no existe constraint singleton.
- **Impacto:** duplica la raíz organizacional y rompe el contexto inicial.
- **Causa raíz / fix:** fast-path sin serialización. **Fix:** reutiliza el advisory lock de bootstrap y re-chequea el holding dentro de la transacción; un request gana y el otro recibe 409.

### BUG-028 — Rotación concurrente de refresh token puede generar dos hijos válidos

- **Módulo / paso del ROADMAP:** accounts/auth / seguridad
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** refrescar simultáneamente la misma sesión/token desde dos conexiones.
- **Esperado:** un 200, un 401 y un único descendiente activo.
- **Actual:** la sesión padre se lee sin lock; ambos requests pueden crear un hijo antes de revocarla.
- **Impacto:** debilita rotación y detección de replay de credenciales.
- **Causa raíz / fix:** la sesión padre se revocaba después de crear el hijo sin lock. **Fix:** transición bajo `transaction.atomic()` y `select_for_update`; prueba real: `[200, 401]` y un único hijo activo.

### BUG-027 — Diagnostics mezcla y expone incidentes entre empresas

- **Módulo / paso del ROADMAP:** diagnostics / aislamiento multiempresa
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** con permiso scoped en empresa A, listar/detallar/triagear un `ErrorEvent` de B; generar el mismo stack en A y B.
- **Esperado:** eventos y deduplicación aislados por empresa.
- **Actual:** las vistas consultan globalmente y el dedupe usa sólo `stack_hash`, conservando el scope del primer incidente.
- **Impacto:** fuga de stack/rutas y mutación cross-tenant; métricas mezcladas.
- **Causa raíz / fix:** vistas y dedupe globales. **Fix:** FKs tenant con backfill, constraints scoped/global y scope de list/detail/run/IA/triage; matriz A/B incluida.

### BUG-026 — Integration Inbox es global y mutable desde otro tenant

- **Módulo / paso del ROADMAP:** integration / aislamiento multiempresa
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** con permisos de integración en A, listar o hacer ACK por ID a un evento originado en B.
- **Esperado:** eventos tenant-scoped; acceso global sólo con permiso de plataforma.
- **Actual:** `InboxEvent` no materializa company/branch y list/ACK operan sobre el conjunto global.
- **Impacto:** fuga de metadatos y cambio de estado cross-tenant.
- **Causa raíz / fix:** Inbox no materializaba el scope del Outbox. **Fix:** FKs company/branch, backfill, check/índice y list/ACK scoped por empresa+sucursal.

### BUG-025 — Documents acepta una sucursal perteneciente a otra empresa

- **Módulo / paso del ROADMAP:** documents / aislamiento multiempresa
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** autenticado en empresa A, subir un documento con `branch_id` de B.
- **Esperado:** 404/422 y cero filas creadas.
- **Actual:** la rama se resuelve por ID/tipo sin exigir `parent=company` y se persiste A+B.
- **Impacto:** corrupción de scope y acceso cruzado a documentos.
- **Causa raíz / fix:** lookup de rama sólo por ID/tipo. **Fix:** scope en API, validación en servicio/modelo, reparación histórica y prueba A/B.

### BUG-024 — Cobros de facturación mezclan importes nominales de monedas distintas

- **Módulo / paso del ROADMAP:** facturación/contabilidad / dinero
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** registrar un pago USD sobre una factura NIO.
- **Esperado:** rechazo hasta que exista conversión FX contablemente completa.
- **Actual:** el pago acepta moneda arbitraria y `amount_paid` suma importes nominales.
- **Impacto:** saldos, cartera y estado PAID incorrectos.
- **Causa raíz / fix:** faltaba política de moneda. **Fix:** normaliza y exige moneda igual a la factura; una distinta devuelve 422 y no crea pago.

### BUG-023 — La idempotencia de cobros existe en servicio pero no está cableada a la API

- **Módulo / paso del ROADMAP:** facturación / dinero
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** repetir el mismo POST HTTP de cobro o hacer doble clic.
- **Esperado:** el segundo request devuelve el mismo pago sin volver a sumar.
- **Actual:** el serializer/vista no aceptan ni propagan `idempotency_key`; cada request crea un pago.
- **Impacto:** doble cobro y factura inflada por retries normales.
- **Causa raíz / fix:** serializer/vista omitían la clave. **Fix:** clave obligatoria de 96 caracteres, constraint por empresa, 201 nuevo y 200 `idempotent=true` en replay; consumidores adaptados.

### BUG-022 — Pagos de facturación no respetan el scope de sucursal ni el doc_id al revertir

- **Módulo / paso del ROADMAP:** facturación / aislamiento por sucursal
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** desde sucursal B usar IDs de una factura/pago de sucursal A para listar, cobrar o revertir.
- **Esperado:** 404 y cero mutaciones fuera de la sucursal activa.
- **Actual:** pagos filtran sólo por empresa y la reversa ignora el `doc_id` de la URL.
- **Impacto:** lectura y movimiento de dinero cross-branch.
- **Causa raíz / fix:** pagos filtraban sólo empresa y reversa ignoraba el documento de la URL. **Fix:** scope `company+branch+doc+payment` y matriz adversarial A/B.

### BUG-021 — El gate frontend da falsos verdes mientras la SPA no compila

- **Módulo / paso del ROADMAP:** frontend/QA / transversal
- **Fecha:** 2026-08-08
- **Severidad:** alta
- **Estado:** CERRADO
- **Pasos para reproducir:** ejecutar los CLI reales de ESLint, vue-tsc y Quasar en vez de los binarios locales vacíos.
- **Esperado:** el gate ejecuta herramientas reales y el build termina verde.
- **Actual:** ejecutables de `node_modules/.bin` de 0 bytes retornan éxito; el build real falla en Intereses, Conteo físico y Captura de campo.
- **Impacto:** CI/certificaciones no detectan una SPA que no construye y pantallas rotas.
- **Causa raíz / fix:** una instalación local corrupta dejó launchers de `node_modules/.bin` vacíos y el gate no verificaba que las herramientas se ejecutaran. **Fix:** `npm ci`, preflight `verify-toolchain.mjs` antes de lint/typecheck/test/build y corrección de los errores reales en Intereses, Conteo físico, Captura de campo y hallazgos de lint. Verificado con lint/typecheck/build reales y 26/26 Vitest.

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

> **Nota de numeración:** BUG-010..013 viven en la rama `fix/aislamiento-copa-nomina` (PR-9, sin
> mergear). Este lote de bug-hunt de integridad (rama `fix/integridad-inventario-facturacion-intercompany`,
> off `main`) usa **BUG-014..020** para no colisionar.

### BUG-020 — Comisariato: `collecting_company` cross-company sin relación CXC declarada

- **Módulo:** comisariato / cobro por planilla — lente L1 (IDOR/authz)
- **Fecha:** 2026-07-04 · **Severidad:** media · **Estado:** CERRADO
- **Reproducir:** `AccountUpsert` (o `get_or_create_account`) con `collecting_company` = una empresa cualquiera.
- **Esperado:** el cobro cross-company solo procede con relación `IntercompanyRelationship` tipo CXC activa.
- **Actual:** resolvía `collecting_company` de cualquier `OrgUnit` COMPANY sin verificar el vínculo → una empresa podía apuntar el cobro de su cuenta a la planilla de otra sin relación.
- **Causa raíz / fix:** faltaba el gate. **Fix:** `get_or_create_account` exige `_has_active_cxc_relationship(finca=collecting, comisariato=company)` cuando `collecting != company` (mismo gate del cobro por planilla). Test: `comisariato/tests/test_comisariato.py::test_collecting_company_sin_relacion_cxc_rechazada`.

### BUG-019 — Portfolio: Receivable/Payable/Credit/Allocation ViewSets con FKs escribibles sin scope (IDOR de escritura)

- **Módulo:** portfolio (kernels) — lente L1. Mismo patrón que BUG-011 (que solo cerró Allocation).
- **Fecha:** 2026-07-04 · **Severidad:** media · **Estado:** CERRADO
- **Reproducir:** `POST /portfolio/receivables|payables|credits|allocations/` con un FK (`party`, `restructured_from`, `payment_intent`, obligación) de OTRA empresa.
- **Esperado:** no se puede crear una obligación de la empresa A que referencie datos de B.
- **Actual:** eran `ModelViewSet` con FKs escribibles y queryset sin scope; solo `company` se forzaba. Se creaba una CxC/CxP/crédito/aplicación con datos de otra empresa, saltándose los servicios.
- **Impacto:** contamina los libros de A con maestros de B y filtra IDs de otra empresa. Es un vector concreto de "mezcla de cuentas".
- **Causa raíz / fix:** las obligaciones se crean EXCLUSIVAMENTE por servicios scopeados (ventas/compras/financiamiento/intercompany). **Fix:** los cuatro ViewSets pasan a `ReadOnlyModelViewSet` (conservando las `@action` de servicio adjust/writeoff/disburse). Test: `portfolio/tests/test_viewsets_readonly.py`. (Nota: incluye Allocation, ya cerrado por BUG-011 en la rama aislamiento; al mergear ambos PRs la línea coincide.)

### BUG-018 — Intercompany: posteo directo se salta las 3 defensas del motor (doble cargo, período cerrado, FX)

- **Módulo:** modulos/intercompany — lentes L2 (concurrencia) + L3 (integridad contable)
- **Fecha:** 2026-07-04 · **Severidad:** alta · **Estado:** CERRADO
- **Reproducir / Actual (3 fallos):**
  - **IC-1:** dos `POST /intercompany/charge` simultáneos con el mismo `reference_code` → idempotencia por `.filter().first()` sin lock ni constraint → DOBLE CxC/CxP + doble asiento en cada empresa + descuadra la consolidación.
  - **IC-2:** `_post_balanced_entry` posteaba en un período CERRADO (los otros 3 posteos sí lo bloquean).
  - **IC-3:** el asiento GL hardcodeaba `NIO`/`fx_rate=1.0` sin importar la moneda → GL subvaluado para moneda ≠ NIO.
- **Causa raíz / fix:** era un camino de posteo directo (I-01) que nunca ganó los guards del motor. **Fix:** (IC-1) `UniqueConstraint(source, target, reference_code)` parcial + `pg_advisory_xact_lock` + re-chequeo; (IC-2) `raise` si el período está CLOSED; (IC-3) rechaza moneda ≠ funcional (NIO) hasta soportar FX real. Migración `accounting/0016`. Tests: `intercompany/tests/test_intercompany_ops.py::test_ic{1,2,3}_*`.

### BUG-017 — Facturación: `create_payment` cobraba borradores/cotizaciones y no era idempotente

- **Módulo:** facturacion — U9 · L2
- **Fecha:** 2026-07-04 · **Severidad:** media-baja · **Estado:** CERRADO
- **Reproducir:** cobrar un DRAFT/QUOTE (solo bloqueaba VOIDED); o doble-submit del mismo cobro.
- **Actual:** se registraba un pago sobre un doc no emitido; un doble-clic creaba dos `BillingPayment` e inflaba `amount_paid`.
- **Causa raíz / fix:** faltaban el gate de estado y el backstop de idempotencia. **Fix (BUG-T5):** exige `status==ISSUED` y `doc_type==INVOICE`. **Fix (BILL-1):** campo `idempotency_key` + `UniqueConstraint(doc, idempotency_key)` parcial + replay bajo el lock del doc. Migración `facturacion/0011`. Tests: `test_cobro_idempotente.py`.

### BUG-016 — Inventario: ajuste / conteo físico no tocaban `LotBalance` (Σ lotes ≠ saldo)

- **Módulo:** inventarios (kernel) — U8
- **Fecha:** 2026-07-04 · **Severidad:** media · **Estado:** CERRADO
- **Reproducir:** ítem con `track_lots`; `post_adjust`/`approve_physical_count` a una cantidad distinta.
- **Actual:** movía `StockBalance` pero dejaba los `LotBalance` intactos → `Σ LotBalance ≠ StockBalance` → rompe FEFO/FIFO y el costeo por lote.
- **Causa raíz / fix:** `post_adjust` no era consciente de lotes. **Fix:** acepta `lot_id` opcional y reconcilia los `LotBalance` en orden de consumo (baja de los más antiguos primero; alza al primero del orden) manteniendo el invariante. Test: `inventarios/tests/test_adjust_lotes.py`.

### BUG-015 — Facturación: anular una factura con efectos dejaba kardex y cartera desalineados de la contabilidad

- **Módulo:** facturacion — U9
- **Fecha:** 2026-07-04 · **Severidad:** alta · **Estado:** CERRADO
- **Reproducir:** emitir factura que despacha inventario y/o genera CxC; anularla (`void_doc`).
- **Actual:** `void_doc` solo revertía el asiento GL; el stock despachado NO volvía al kardex y el `Receivable` quedaba OPEN → subledgers divergentes de la contabilidad.
- **Causa raíz / fix (decisión del usuario):** anular es solo para documentos SIN efectos. **Fix:** `void_doc` bloquea (con mensaje que remite a Nota de Crédito) si el doc tiene inventario despachado, CxC generada o abonos. La Nota de Crédito ya reingresa stock y ajusta cartera. Test: `test_void_bloquea_con_efectos.py`.

### BUG-014 — Inventario: transferencia entre bodegas no mezclaba el costo promedio del destino

- **Módulo:** inventarios (kernel) — U8
- **Fecha:** 2026-07-04 · **Severidad:** alta · **Estado:** CERRADO
- **Reproducir:** `post_transfer` de A→B; luego despachar de B.
- **Actual:** el destino solo actualizaba `avg_cost` si la cantidad final era 0 (imposible en una entrada) → a bodega vacía quedaba `avg_cost=0` (COGS=0 y valorización 0); a bodega con stock a otro costo, no promediaba (subvaluación).
- **Impacto:** COGS y valorización de inventario erróneos en operación normal (transferencias entre bodegas son cotidianas).
- **Causa raíz / fix:** faltaba la mezcla ponderada. **Fix:** el destino promedia `avg_cost` como `post_receive` (con el reinicio INV-02 sobre base cero/negativa). Test: `inventarios/tests/test_transfer_costeo.py`.

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
