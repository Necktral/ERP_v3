# Plan de trabajo — Cartografía, documentación y fortalecimiento de ERP_v3

> **Estado:** APROBADO. **La Fase 0 está CERRADA** (Compuerta 0, 2026-10-05) y el **rumbo pasó a la V4** (§0). Se ejecuta por fases con una parada en cada compuerta. El detalle de la Fase 0 está en `LOG.md` · **Fecha:** 2026-10-04 · **Corregido:** 2026-10-05, con lo que encontró la Fase 0
> **Código base:** rama `fix/integridad-inventario-facturacion-intercompany`, commit `dace480` (2026-08-18)
> **Mandan:** `ARQUITECTURA_V3.md` y `CLAUDE.md`. Si este plan contradice algo de ahí, gana el norte y se avisa.

---

## 0. Rumbo actualizado (D-06, 2026-10-05)

Wis decidió **reconstruir el sistema como ERP_V4** (`/home/wis/dev/ERP_V4`). La V4 no parte de cero: **se copia v3 módulo por módulo** y la cartografía (F1) y la documentación (F2) se hacen **al integrar cada módulo**. Así no se mapea dos veces, y lo que se documenta es el sistema que va a quedar.

**Lo que cambia de este plan:**
1. **Antes de copiar** se hace un **mapa global liviano de v3** con las capas C1 (inventario), C3 (integración) y C5 (promesas). Define el orden de copia y las reglas que la V4 tiene que cumplir.
2. **Se diseña el esqueleto de la V4.** Su pieza central es un **contrato de módulo**: cómo cada módulo declara sus modelos, rutas, permisos, eventos y menús, para que se pueda integrar cualquier módulo. Wis lo aprueba como documento.
3. **Los módulos se copian uno por vez,** en el orden de la constitución: plataforma → contabilidad → HR → nómina → inventario → compras → ventas/POS → caja → payments → portfolio → reportes. **Ninguno entra sin pasar su compuerta:**
   - su ficha (C2) y sus flujos (C4);
   - su documentación;
   - sus pruebas copiadas y en verde;
   - las guardias;
   - el veredicto del auditor.
4. **La caza de bugs (F3)** se hace sobre la V4 a medida que se arma el ciclo de negocio. **El fortalecimiento (F4)** queda incorporado a la integración de cada módulo.
5. **v3 sigue como respaldo del demo.** La V4 copia el código **ya corregido**: el port de PR-9 una vez aprobado, y BUG-075 resuelto.

Las secciones que siguen describen el programa original. Las Fases 1 a 4 se reorganizan bajo este rumbo y su detalle se planifica, en modo plan, al terminar la Fase 0.

**Precisión de Wis (2026-10-05):** la V4 tiene que ser modular, segura y sin complicaciones innecesarias, con pruebas que corran mientras se construye, y **reconstruida desde cero**.

**Propuesta:** que sea desde cero en la base y no en las reglas.
- El esqueleto se escribe nuevo.
- Las reglas legales y contables de v3 se traen una por una, cada una en un solo lugar y con su prueba.

**El motivo es C-21, hoy BUG-080:** el bug no salió de copiar código, sino de tener la misma regla, el neto, escrita en tres lugares con fórmulas distintas. Esto se cierra en el plan de la V4.

---

## 1. Qué buscamos

Son tres resultados, en este orden, y cada uno alimenta al siguiente:

1. **Un mapa completo del software.** Qué existe, qué hace cada pieza, cómo se conectan y qué pasa de verdad cuando alguien hace una operación. Todo con evidencia, nada de memoria.
2. **La documentación al día.** El mapa pasa a ser la documentación oficial: una sola fuente de verdad, fácil de recorrer.
3. **Los bugs encontrados** en frontend, backend y lógica de negocio. El mapa dice dónde buscar, y al final queda un backlog con prioridades para fortalecer el sistema antes del demo.

---

## 2. Punto de partida

### 2.1 Lo que ya está hecho y no se repite

La auditoría forense de agosto (30 unidades y 5 lentes, cierre técnico PASS el 2026-08-18) certificó la parte técnica: aislamiento entre empresas, permisos, concurrencia, idempotencia, integridad contable, migraciones y accesibilidad. Cerró todos los bugs que estaban registrados en esa rama y dejó en verde 2,072 pruebas backend, 59 de Vitest y 4 de Playwright.

**Precisiones de la Fase 0 (línea base del 2026-10-05):**
- El código de `dace480` está sano: 2,073 pruebas backend en verde, 59/59 Vitest y los contratos al día.
- Las "2,072" no incluyen **7 carpetas de pruebas que ningún gate corre**. Son 203 pruebas y también pasan.
- El "PASS" de agosto **no se puede reproducir con sus propios gates**: el static scan ya estaba rojo con la evidencia versionada ese mismo día, por falsos positivos con la palabra "TODO".
- Detalle completo: `.evidencia/dace48003f5a/…-baseline/comparacion_agosto.md`.

**Este plan no repite esa auditoría.** La toma como base y vuelve a correr sus guardias como regresión sobre el código actual.

### 2.2 Primer hallazgo, ya comprobado en el código

`BUGS.md` reserva los números BUG-010 a BUG-013 con una nota ("viven en la rama PR-9, sin mergear"). No es un salto de numeración: son **cuatro bugs reales, dos de severidad ALTA**. Se encontraron y se arreglaron el 2026-07-03 en la rama `fix/aislamiento-copa-nomina` (commit `6e408f3`, el PR-9 que quedó pendiente), y esa rama **nunca se integró**. La auditoría de agosto se hizo sobre la otra línea, así que no los vio. Así están hoy en `dace480`:

| Bug | Qué pasa | ¿Está arreglado en `dace480`? |
|---|---|---|
| **BUG-011** (ALTA). Una empresa podía aplicar pagos a deudas de otra | El endpoint de aplicaciones aceptaba cruzar el pago de una empresa con la deuda de otra, sin pasar por el servicio | **A medias.** La API está cerrada desde BUG-019 (`PaymentAllocationViewSet` es de solo lectura), pero faltan las defensas de servicio. `allocate_payment_to_obligation` no compara empresas, aunque el docstring de la vista diga que sí. El abono de planilla y el descuento de comisariato tampoco exigen la relación entre empresas |
| **BUG-012** (ALTA). La Sala de pago (CO-PA) sin conexión | Al sincronizar, cada pago de la cola se sube con la empresa que está **activa** en ese momento y no con la suya. Si el pagador paga sin señal en la finca A y sincroniza estando en la B, el servidor responde 404 y la cola marca el pago como FAILED. Como `isDue` no excluye FAILED, se reintenta en cada drenado, pero **solo entra si se drena con A activa**. Mientras tanto, el trabajador ya recibió el efectivo, el pago no está registrado y los contadores mezclan empresas. | **No.** `sincronizar()` en `pagador/pages/SalaDePagoPage.vue` no pasa la empresa del comando, `payEntry` (`pagador/api.ts:183`) no fija `X-Company-Id` y el interceptor pone la empresa activa (`boot/axios.ts:212-220`). Un 4xx pasa a `FAILED` (`classifyError`), pero `isDue` lo vuelve a tomar en cada drenado (`pagador/offline/queue.ts:104`) |
| **BUG-013**. "Recalcular" una planilla ya pagada | La acción `compute` recalcula aunque el período esté aprobado, pagado o cerrado, o aunque ya tenga pagos, y puede revertir un cobro CO-PA ya aplicado. Ese saldo vuelve a quedar como pendiente de pago. | **No.** En `kernels/nomina/views.py`, `PayrollSheetActionView` (acción `compute`) llama a `compute_all_entries_in_sheet` sin la compuerta 409 |
| **BUG-010**. El respaldo en base de datos de la idempotencia de pagos de planilla | A `PayrollPayment` le falta `UniqueConstraint(entry, reference)`. La idempotencia en la aplicación sí existe. | **No.** Además, la migración de ese arreglo (`0020_payrollpayment_uq_paypay_entry_ref`) **choca** con la `0020_hash_biometric_device_tokens` de la línea actual |

**Resultado de la Fase 0:** los cuatro se reprodujeron con pruebas rojas sobre `dace480`.
- Apareció **BUG-074**, de la misma familia que BUG-013: otros seis caminos alteran una planilla ya cobrada o aprobada.
- El arreglo de julio de BUG-012 **no servía tal cual**: sin sucursal activa perdía todos los pagos.

Todo se preparó en la rama aparte `fix/pr9-copa-nomina-port`, con rojo→verde y un auditor independiente por bug, y **espera tu revisión** (`docs/cartografia/REVISION_PR9.md` en esa rama).

**Hallazgo crítico fuera del port (BUG-075).** Es una falla de seguridad en el sync, confirmada en la base aislada. El detalle queda reservado hasta el arreglo, en la evidencia local.

**Qué cambia en el plan:** la cartografía mapea también **las ramas**, y no solo el código de una de ellas.

### 2.3 Lo que quedó abierto, que es justo lo que ataca este plan

| Hueco | Evidencia |
|---|---|
| **La validación de negocio con el usuario del campo** | `ROADMAP.md`: el Paso 1 está DONE, el Paso 2 está DOING desde el 2026-08-08 y los Pasos 3 a 10 están en TODO. `ARQUITECTURA_V3.md` §1 dice que el problema de v2 eran los bugs "de uso vivo". La auditoría de agosto fue técnica y no los cubre. |
| **El ciclo completo nunca se corrió de punta a punta** | Compra → inventario → venta → caja → cobro → nómina → cierre, sobre una DB limpia y con datos creados a mano. Hubo pruebas por unidad y un integrador de 15 casos, pero nunca una operación continua con los libros conciliados. |
| **Reglas legales sin visto bueno** | En `docs/CUMPLIMIENTO_NICARAGUA_2026.md` siguen abiertos LEGAL-PEND-001 a 004 (complemento fuera de INSS/IR, umbral patronal de 50, salario mínimo oficial y casos dorados), y los tres vistos buenos están PENDIENTES. |
| **Documentación desfasada** | `README.md` está vacío (8 bytes). `ROADMAP.md` dice que la auditoría profunda está "pendiente de ejecutar", pero ya se ejecutó. `BUGS.md` tiene unos 40 bugs CERRADOS bajo el título "Bugs abiertos". `GUIA_MAESTRA.md` quedó congelada en julio (218 migraciones, BUG-002 abierto, push pendiente). `ARQUITECTURA_V3.md` §5 y §10 todavía muestran como pendiente la decisión de una o dos empresas, que ya se tomó. Hay 13 README y bitácoras repartidos por el código sin índice, y 83 reportes versionados en `qa/reports/` que mezclan julio y agosto. |
| **El entorno cambió** | Ahora se trabaja en Linux nativo, no en WSL. El worktree `ERP_v3_forensic` apuntaba a `/mnt/wsl/…`; **ya se reparó en la Fase 0** y ahora trabaja en `audit/cartografia-2026-10`, creada desde `dace480`. Además, los `docker compose` y `make qa-*` sin proyecto **apuntan al demo**: se resolvió con el envoltorio `erpbl` (BUG-076). |
| **Ramas sin destino** | `fix/integridad-…` tiene 88 commits locales. `fix/aislamiento-copa-nomina` tiene 3 commits sin integrar (el PR-9, ver 2.2). `preserve/pre-forensic-20260818` es el respaldo previo a la auditoría. **GitHub no se usa (D-05):** todo se integra con merges locales. |

### 2.4 Tamaño del terreno

| Capa | Medida al 2026-10-04 |
|---|---|
| Backend (Django) | 7 kernels y 35 carpetas de módulos (30 apps instaladas, 4 cascarones de compatibilidad y `sync` vacío) · ~107 k líneas de código · ~70 k líneas de pruebas · 226 migraciones · 508 rutas API · 853 rutas OpenAPI |
| Kernels más grandes | accounting 19.6 k · nomina 10.1 k · facturacion 6.5 k · reporting 5.1 k · inventarios 4.6 k |
| Frontend (Vue 3 + Quasar + Capacitor) | 34 módulos · ~63 k líneas · 107 páginas · ~129 rutas · 19 archivos de Vitest · 1 archivo de Playwright (4 pruebas) |
| QA existente | 62 guardias y scripts en `qa/` (rutas↔permisos, drift API↔frontend, OpenAPI, arquitectura, migraciones, cobertura por dominio, drift v2↔v3) |
| Documentación | 37 archivos `.md` |

---

## 3. Reglas del programa

- **Solo lectura** sobre `../ERP_v2` y sobre la DB del demo (proyecto docker `erp_crm`, con los contenedores `erpcrm_*` y el volumen `erp_crm_pgdata`). Todo se corre en un stack aislado propio.
- **Lo que se valida se crea a mano, por la interfaz**, siguiendo el arranque de la constitución. El seed se queda como taller del desarrollador.
- **Sin evidencia, no cuenta.** Cada afirmación del mapa lleva `archivo:línea`, un comando o una captura.
- **Primero `BUGS.md`**, después la prueba roja y recién después el arreglo.
- **Nada se da por terminado porque lo diga un agente.** Cada fase cierra con una compuerta que revisa alguien distinto de quien hizo el trabajo. `LOG.md` se actualiza al cerrar cada lote, para poder retomar si se corta la sesión.
- **Primero el alcance del demo**: contabilidad, HR y asistencia, nómina, inventario, compras, ventas y POS, caja, payments, portfolio y reportes. Los módulos dormidos se cartografían, pero la caza profunda espera a que se enciendan.
- **Todo docker y todo make pasan por `docs/cartografia/stack/erpbl`.** Sin el envoltorio, `docker compose` y `make qa-*` apuntan al demo (BUG-076). Antes de cada comando, el envoltorio verifica el proyecto, los volúmenes, los puertos, los montajes y la huella del demo.
- **No se usa GitHub (D-05):** sin push, sin PR y sin fetch. Las ramas se integran con merges locales.

---

## 4. Fase 0 — Preparar el terreno (ejecutada el 2026-10-04/05; detalle y evidencia en `LOG.md`)

| # | Tarea | Resultado |
|---|---|---|
| 0.1 | Seguridad y git: el envoltorio `erpbl`, la huella T0 del demo, un `pg_dump` de solo lectura, un vigilante de eventos, `worktree repair`, la rama del programa y el worktree del port | El demo quedó intacto: misma huella en todo momento y ningún evento real. Git funciona en el forense |
| 0.2 | Stack aislado `erpv3_baseline` con la DB vacía | 226 migraciones desde cero. La API y el frontend responden |
| 0.3 | Línea base sobre `dace480`, paso por paso | El código está sano. Cada rojo quedó clasificado (proceso, fecha, aviso vivo, falso positivo o entorno). La evidencia está sellada. Playwright espera la descarga de Chromium |
| 0.4 | 10 agentes `erp-*` en `.claude/agents/` | Calibrados: el verificador acertó 4/4 y el auditor detectó los defectos plantados |
| 0.5 | El port de PR-9 y BUG-074, **aparte** (`fix/pr9-copa-nomina-port`) | Rojo→verde en cada bug y un auditor independiente por bug. Espera tu revisión |
| 0.6 | Cierre: este plan corregido, BUGS.md, el LOG y la verificación de un tercero | Ver la Compuerta 0 en `LOG.md` |

## 5. Fase 1 — Cartografía: el mapa del sistema (≈ 4 a 6 jornadas)

El mapa se arma en siete capas y va de lo mecánico a lo que pide criterio. **Lo que puede sacar un script lo saca un script**, porque es exacto y se puede regenerar. Lo que hay que leer y entender lo hacen agentes cartógrafos con una plantilla fija.

| Capa | Pregunta | Cómo se obtiene | Salida |
|---|---|---|---|
| **C1 Inventario mecánico** | ¿Qué existe? | Scripts que reutilizan las guardias de `qa/`: rutas y permisos, OpenAPI, modelos con sus campos y relaciones, rutas y llamadas del frontend, módulos encendidos por empresa, tamaño y complejidad, churn de git, qué prueba cubre cada módulo, y ramas y commits sin integrar | `docs/cartografia/inventario/` (JSON regenerable y un resumen) |
| **C2 Fichas de módulo** | ¿Qué hace cada pieza? | Cartógrafos que trabajan por lote de dominio (43 del backend y 34 del frontend) | Una ficha por módulo: propósito, modelos, servicios, endpoints, pantallas, permisos, eventos que emite y consume, pruebas, estado en el demo, origen en v2 y bugs históricos |
| **C3 Integración** | ¿Quién depende de quién? | El grafo de imports, el grafo de eventos (EconomicEvent → regla de posteo → cuentas) y las señales | Hubs, capas, ciclos y piezas aisladas |
| **C4 Flujos de negocio** *(el corazón)* | ¿Qué pasa de verdad cuando alguien hace X? | Seguir cada operación de pantalla a endpoint, servicio, kernels y asiento, con sus efectos (stock, CxC/CxP, caja) hasta el reporte | Un documento por flujo con su diagrama de secuencia (lista abajo) |
| **C5 Reglas e invariantes** | ¿Qué reglas tiene que cumplir y dónde se hacen cumplir? | Un cartógrafo de "promesas" lee ARQUITECTURA, CLAUDE, GUIA, CUMPLIMIENTO y el runbook de agosto, y lo cruza con el código | Un catálogo con la regla, su fuente, dónde vive en el código, su prueba y su estado (*cubierta*, *parcial*, *sin prueba* o *divergente*) |
| **C6 Pantallas** | ¿El usuario del campo puede completar la tarea? | Recorrer cada página del alcance del demo anotando rol, pasos, clics, estados de carga, vacío y error, mensajes y cómo se ve en tablet | Un catálogo de pantallas medido contra los 7 criterios |
| **C7 Mapa de calor** | ¿Dónde es más probable que haya bugs? | Cruzar churn, complejidad, historial de bugs, densidad de pruebas y peso en el demo | Una lista de zonas calientes, ordenada por prioridad, para la Fase 3 |

**Flujos que se trazan en C4.** Son los del supermercado de `ARQUITECTURA_V3.md` §4, más los administrativos:

1. Arranque: admin temporal → empresa → empleado-administrador → baja del admin temporal
2. Apertura de caja con arqueo por denominación
3. Compra a crédito: orden → recepción → inventario → CxP → asiento
4. Venta de contado en el POS, incluyendo el trabajo sin conexión y la reconexión
5. Venta a crédito: límite, aprobación y CxC
6. Devolución y anulación
7. Cierre de caja y arqueo
8. Pago a proveedor y conciliación
9. Cobro a cliente y aplicación a la cartera
10. Asistencia (biométrico y campo) → planilla → pago → asiento, con el neto legal intacto. Incluye la Sala de pago sin conexión
11. Cobro de la deuda del trabajador vía portfolio, después de cerrar la planilla
12. Cierre del período contable y reportes al dueño
13. *(Hito posterior)* Intercompany entre dos empresas

**Cómo se verifica el mapa.** Se comparan las promesas con el código real y salen las **brechas**, de cuatro tipos: *implementado y prometido*, *implementado sin respaldo*, *prometido y ausente* y *divergente*. Después, un verificador de contexto fresco revisa una muestra y al final se hace la síntesis.

**Compuerta 1:** todos los módulos tienen ficha, los flujos 1 a 12 están trazados de punta a punta, el catálogo de reglas tiene el estado de cada una, existe la lista de brechas, en la muestra verificada se confirma el 90 % o más (lo refutado se corrige) y el LOG está al día.

---

## 6. Fase 2 — Actualizar la documentación (≈ 2 a 3 jornadas)

**2.1 Clasificar lo que hay.** Cada uno de los 37 `.md` queda como *vigente*, *desactualizado* (se corrige), *histórico* (se conserva marcado y no se borra) o *duplicado* (se fusiona).

**2.2 Una sola fuente de verdad:**

| Documento | Qué se hace |
|---|---|
| `README.md` | Se escribe de cero: qué es, cómo se levanta y dónde está cada cosa |
| `docs/README.md` | Índice de toda la documentación |
| `docs/sistema/` | El mapa pasado a documentación: visión general, fichas de módulo, flujos, reglas de negocio, modelo de datos, catálogo pantallas↔API, integración y operación |
| `ROADMAP.md` | El estado real de los 10 pasos y de este programa. Se quita lo que ya no aplica |
| `BUGS.md` | Un índice con estado, severidad, capa y módulo, cada bug en su sección y BUG-010 a 013 incorporados |
| `GUIA_MAESTRA.md` | Se actualizan el estado actual, los módulos y los bugs |
| `ARQUITECTURA_V3.md` | Solo se marcan las decisiones que ya se tomaron. **El norte no se cambia sin tu aprobación** |
| `CLAUDE.md` / `AGENTS.md` | Se mantienen sincronizados y apuntan al mapa |
| `docs/historico/` | El runbook del escaneo profundo y los registros de agosto, marcados como históricos |
| Guías de usuario por tarea *(opcional)* | Una hoja por tarea del campo, con capturas, para el demo |

**2.3 Que no vuelva a envejecer.** Lo mecánico se regenera con un script, y una guardia simple avisa cuando un documento cita rutas, archivos o endpoints que ya no existen.

**Regla:** se documenta lo que **es** y no lo que debería ser. Si el código se aparta de lo prometido, eso va a la lista de brechas y a `BUGS.md`, sin maquillarlo en el documento.

**Compuerta 2:** los 37 documentos están clasificados, README, ROADMAP, BUGS y GUIA están corregidos, `docs/sistema/` está completo y no queda ningún enlace interno roto.

---

## 7. Fase 3 — Caza de bugs guiada por el mapa (≈ 5 a 8 jornadas, más las sesiones con usuario)

Son cuatro frentes, en orden de prioridad.

### 3A. Lógica de negocio, la prioridad máxima

- **"Un mes comprimido" de una empresa como Comisariato Santa Isabel.** En el stack aislado y por la interfaz real, se recorren los 10 pasos con pocos datos pero con el ciclo completo: 2 trabajadores, 5 productos, 2 proveedores, 3 clientes, una semana de operación, una planilla y un cierre de mes. Después de cada paso **se concilian los libros**:
  - el inventario valorizado es igual a la cuenta de inventario
  - el saldo de CxC es igual a la cuenta control de clientes, y el de CxP a la cuenta control de proveedores
  - la caja del sistema es igual al arqueo físico
  - la balanza de comprobación cuadra
  - el neto legal del trabajador queda intacto
- **Casos dorados legales:** nómina mensual, quincenal y de jornalero, séptimo día, horas extra, vacaciones, aguinaldo, umbral patronal de 50, tramos de IR, y el IVA y las retenciones en facturación. Hace falta que Wis o el contador den los resultados esperados (LEGAL-PEND-004).
- **Casos de borde:** devolución parcial, anulación con efectos, crédito excedido, stock en cero, operación en un período cerrado, USD/NIO y redondeos, doble clic, y el POS y la Sala de pago que se reconectan después de cambiar de empresa.
- **Brechas del mapa:** cada promesa ausente o divergente se revisa como posible bug.

### 3B. Backend

- Volver a correr las guardias de agosto sobre el código nuevo: seguridad, concurrencia y contratos.
- Recorrer la API contra el OpenAPI con datos inválidos. No tiene que salir ningún error 500 ni ningún código crudo.
- Buscar validaciones que rechazan en seco en vez de guiar, revisar los permisos por rol en los flujos del demo y detectar consultas repetidas (N+1) en esos flujos.

### 3C. Frontend

- Recorrer con un navegador real cada pantalla del demo, con cada rol (admin, contador, cajero, planillero) y en 3 tamaños (móvil, tablet y escritorio). Se buscan errores de consola, llamadas fallidas, códigos crudos, estados de carga, vacío y error, y pantallas sin salida.
- Revisar el contrato pantalla↔API: campos que la pantalla espera y el backend no manda, y al revés.

### 3D. El usuario del campo y los 7 criterios

- Un guion por cada paso del ROADMAP, para que una persona real lo haga sin ayuda. Cada tropiezo se registra como bug de UX.

**Protocolo de cada hallazgo:** entra a `BUGS.md` a partir de BUG-074 con su **capa** (FE, BE, NEG o UX), el módulo, la severidad, los pasos para reproducirlo, lo esperado frente a lo que pasa, el impacto y la evidencia. Los críticos y los altos los confirma un verificador de contexto fresco antes de ponerles prioridad.

**Compuerta 3:** se recorrieron los flujos 1 a 12, los libros se conciliaron en cada paso (o el descuadre quedó registrado), se revisaron todas las pantallas del demo, cada hallazgo está registrado y clasificado y existe el informe con el backlog ordenado por prioridad.

---

## 8. Fase 4 — Fortalecimiento (después, por prioridad)

Se arregla por severidad y por impacto en el demo, una pieza a la vez: prueba roja, arreglo mínimo y regresión dirigida y cruzada. Un paso del ROADMAP pasa a DONE solo cuando cumple los 7 criterios. El cierre usa la compuerta agregadora que ya existe (`qa/forensic_closure_guard.py`).

---

## 9. Entregables

| Entregable | Dónde |
|---|---|
| Plan y bitácora | `docs/cartografia/PLAN_CARTOGRAFIA.md` · `docs/cartografia/LOG.md` |
| Inventario regenerable | `docs/cartografia/inventario/` |
| Mapa (fichas, flujos, reglas, integración, pantallas y calor) | `docs/sistema/` |
| Brechas promesa↔código | `docs/cartografia/BRECHAS.md` |
| Bugs nuevos | `BUGS.md` (de BUG-074 en adelante, más BUG-010 a 013 reconciliados) |
| Informe de fortalecimiento y backlog | `docs/cartografia/INFORME_FORTALECIMIENTO.md` |
| Documentación actualizada | `README.md`, `ROADMAP.md`, `BUGS.md`, `GUIA_MAESTRA.md`, `docs/README.md` |

---

## 10. Cómo se ejecuta

- **Roles.** Es el mismo esquema de cartografía que ya usás en RNE, adaptado: cartógrafo de promesas, cartógrafos de código por dominio, analista de integración, analista de brechas, verificador de contexto fresco, sintetizador y preparador de decisiones para vos.
- **Lotes chicos**, un dominio por vez, con el LOG al día al cerrar cada lote. Así no se repite el corte de sesión de julio.
- **Scripts para lo mecánico y agentes para lo que hay que leer.** La verificación siempre la hace alguien independiente.

---

## 11. Calendario tentativo

| Fase | Duración estimada | Arranca cuando |
|---|---|---|
| 0 · Preparar el terreno | 1 a 2 jornadas | Apruebes este plan |
| 1 · Cartografía | 4 a 6 jornadas | Cierre la Fase 0 |
| 2 · Documentación | 2 a 3 jornadas | Avance la Fase 1 (README, ROADMAP y BUGS pueden ir antes) |
| 3 · Caza de bugs | 5 a 8 jornadas, más las sesiones con usuario | Cierren las Fases 1 y 2, y lleguen los casos dorados del contador |
| 4 · Fortalecimiento | Según los hallazgos | Cierre la Fase 3 |

---

## 12. Riesgos y cómo se cubren

| Riesgo | Cobertura |
|---|---|
| Declarar "terminado" antes de tiempo, como pasó en agosto | Compuertas por fase que revisan terceros. Nada cierra porque lo diga un agente |
| Arreglos que se quedan en ramas sin integrar, como BUG-010 a 013 | La cartografía incluye las ramas, y ningún bug se da por cerrado si su arreglo no está en la línea de trabajo |
| Tocar la DB del demo | Un stack aislado con proyecto y volumen propios. **Todo pasa por `erpbl`**, que bloquea el proyecto `erp_crm`, `down -v` y los targets peligrosos, y compara la huella del demo. Hay además un respaldo `pg_dump` y un vigilante de eventos |
| Evidencia que no corresponde a lo que dice | Cada corrida queda sellada con su commit y `SHA256SUMS`. Los reportes van a `.evidencia/`, no a los archivos versionados. Se verifica la frescura de cada reporte |
| Archivos de root en el árbol (escritos por el contenedor) | Lo que genera código fuente se corre como uid 1000. Los directorios de reportes se crean como el usuario del host |
| Que el mapa envejezca | Lo mecánico se regenera y una guardia detecta las referencias rotas |
| Reglas legales sin respaldo profesional | Casos dorados del contador. Los vistos buenos quedan como pendiente humano explícito |
| Dispersarse en los módulos dormidos | Se cartografían, pero la caza profunda es solo del alcance del demo |

---

## 13. Decisiones

**Ya tomadas** (registradas en `LOG.md`):
- **D-01:** el port de BUG-010 a 013 va en una rama aparte, y la revisás antes de que entre.
- **D-02:** el frontend va al final en la caza y en los arreglos.
- **D-03:** se trabaja en el forense, en `audit/cartografia-2026-10`.
- **D-04:** respaldo de solo lectura del demo.
- **D-05:** no se usa GitHub. Queda reemplazada por D-07 solo para el PR del programa.
- **D-06:** el rumbo pasa a la V4, y la cartografía y la documentación se hacen al integrar cada módulo (§0).
- **D-07:** el PR de `audit/cartografia-2026-10` contra `main` se abre al cerrar la Fase 0.
- **Módulos dormidos:** solo se cartografían.

**Pendientes de vos:**
1. **El port de PR-9 (`REVISION_PR9.md`).** ¿Lo integro antes de la Fase 1?
2. **BUG-075 y BUG-080, los dos críticos.**
   - BUG-075: falla de seguridad en el sync (detalle reservado).
   - BUG-080: el CO-PA entrega el neto sin la alimentación.

   ¿Se arreglan en v3, en una rama aparte, porque el demo o la operación los pueden tocar? ¿O se resuelven al integrar sync y nómina en la V4?
3. **La descarga de Chromium 1234** (unos 170 MB) para las 4 pruebas de navegador. Con la V4 pierde prioridad.
4. **El usuario del campo (3D).** ¿Lo hacés vos, o hay un cajero o un planillero real que pueda probar?
5. **Los casos dorados legales.** ¿El contador puede pasar los recibos de planilla esperados (mensual, quincenal, jornalero, vacaciones, aguinaldo y liquidación)?
6. **Las excepciones de seguridad vencidas y los avisos npm.** ¿Se renuevan con justificación o se actualizan las dependencias? Va en la Fase 4.
