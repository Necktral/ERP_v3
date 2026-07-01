# ERP_v3 — Arquitectura y plan de construcción

**Agrícola Santa Isabel** · Holding cafetalero, Jinotega, Nicaragua
Documento norte de v3. Capturado de la sesión de planeación. Esto **no se pierde**: vive en el repo, se actualiza, manda sobre el código.

---

## 1. Por qué existe v3

ERP_v2 **funciona en código**: 828 archivos, 7 kernels probados, contabilidad de doble partida con certificación por fases, nómina legalmente fiel a Nicaragua, intercompany construido, seguridad madura. Es un sistema serio y sirve.

El problema **no es el código**. Es que en **uso vivo, con un usuario real tocando la interfaz**, hay bugs de integración, inconsistencias, flujos que no cierran, estados que confunden. Esos son bugs de UX y de armado, no de lógica.

**v3 no es refactorizar v2. Es reconstruir limpio sobre los kernels probados, pieza por pieza, validando cada una antes de meter la siguiente — y con una interfaz tan simple que la pueda usar gente del campo sin capacitación.**

ERP_v2 **queda intacto como referencia.** No se toca. Solo se deja bien organizado. Es el blueprint del que aprendimos qué funciona y qué no.

---

## 2. El principio rector: simplicidad para el usuario del campo

Esto es lo que hace a v3 distinto, y **manda sobre todas las demás decisiones.**

La gente con la que se trabaja vive en el campo y tiene uso limitado de la computadora — no porque les falte capacidad, sino porque no es su entorno diario. No están adaptados como un usuario europeo o estadounidense. **Hay que llevarlos por un solo camino, y que todo sea intuitivo.**

Implicaciones concretas, no negociables:

- **Flujos lineales.** Paso 1 → paso 2 → paso 3 → listo. Sin ramificaciones confusas, sin pantallas con veinte opciones.
- **Mínimos clics por operación.** Una venta, una compra, una planilla: lo menos posible.
- **Mensajes claros en español, no códigos.** "La venta no se guardó, probá otra vez" en lugar de "Error 500".
- **Validaciones que guían, no que rechazan en seco.** Si falta un dato, decir qué falta y dónde — no botar la operación sin explicar.
- **Apoyo visual: iconos, colores, estados grandes.** No depender solo de texto. Que se vea "acá estás, esto sigue, esto ya quedó".
- **Móvil/tablet-first.** Si se usa en el campo, tiene que andar bien en pantalla chica y con toque.
- **Estados que comunican.** Que el usuario nunca quede sin saber si algo se guardó, falló, o está en proceso.

> Regla de oro de v3: **si un cajero o un planillero del campo no puede completar la tarea sin que nadie le explique, la tarea no está terminada — aunque el código funcione perfecto.**

---

## 3. Los 7 kernels: los cimientos probados

Estos son los bloques de confianza. Se reusan **tal cual**, todos. v3 los orquesta con interfaces limpias encima.

| Kernel | Qué hace | Estado verificado (lectura de código) |
|---|---|---|
| **accounting** | Doble partida event-sourced: EconomicEvent → JournalDraft (maker-checker) → JournalEntry. Períodos fiscales con close/reopen auditado, reglas de posteo versionadas, multimoneda, consolidación. | Espina sólida, nivel auditoría. |
| **nomina** | Cálculo legal nicaragüense (Ley 822, art. 21 LCT), INSS/IR, patronal, séptimo día, subsidios. Submódulos de biométrico y asistencia de campo. | **Net legal inviolable** (ver §6). IR y bases correctas. |
| **inventarios** | Materia prima, productos, costos, movimientos de stock. | Base lista. |
| **facturacion** | Facturas, documentos de venta. | Base lista. |
| **payments** | Cobros y pagos. | Base lista. |
| **portfolio** | Cartera viva: CxC, CxP, obligaciones, deudas, créditos. | Base lista. |
| **reporting** | Visibilidad integrada de todo. | Base lista. |

Además existen primitivos clave ya construidos que v3 aprovecha:

- **Intercompany** — cuando una empresa cobra por cuenta de otra, genera CxC en una, CxP en la otra, y la consolidación lo elimina. Esto significa que **el demo de dos empresas ya no está bloqueado** por ese mecanismo.
- **Régimen INSS fechado** — resuelve el dolor del "shuffle" CON INSS / SIN INSS sin mover gente a mano entre planillas.
- **Arqueo de caja por denominación** y **POS offline-first** ya existen en el kernel/módulo de ventas.
- **seed_dev_environment** — levanta un entorno de demostración reproducible tras cada wipe.

---

## 4. El flujo de la empresa real (el supermercado)

No inventamos nada. Una empresa normal: **compra, vende, tiene trabajadores, paga nómina.** El corazón del negocio es **comprar y vender**, y eso es lo que hay que pulir de punta a punta.

El ciclo de un supermercado, que es el ciclo que v3 tiene que manejar sin un solo descuadre:

**Apertura del día**
- Abrir caja y contar el dinero inicial (arqueo de apertura)
- Verificar stock en góndolas
- Llegan los empleados → fichaje / asistencia

**Durante el día**
- **Compras:** recibir mercadería del proveedor, registrar entrada a inventario, guardar la factura → genera CxP
- **Ventas:** el cliente compra, pasa por caja, se cobra (efectivo, tarjeta, crédito) → si es crédito, genera CxC
- **POS:** la caja registra cada venta y descuenta inventario en tiempo real
- **Devoluciones:** el cliente devuelve, se reembolsa, se reajusta stock
- **Reposición:** los empleados reponen góndolas desde el depósito

**Cierre del día**
- Cierre de caja (arqueo: el dinero físico tiene que cuadrar con el sistema)
- Fin de jornada, se van los empleados
- Queda registrado cuánto se vendió, cuánto se gastó, cuánto quedó en caja
- Inventario actualizado: lo que entró − lo que salió

**Administrativo (periódico)**
- Pagar a proveedores (CxP)
- Cobrar a clientes con crédito (CxC)
- Pagar nómina a empleados
- Reportes al dueño: ganancia, qué se vendió, qué falta

---

## 5. Empresa 1: la empresa completa de demostración

Una sola empresa que **toca todos los kernels** — la prueba de fuego. Como vender y comprar es el centro, el POS con cuentas, crédito e inventario es lo más completo y lo que más hay que pulir.

Empresa 1 necesita en marcha: organización + contabilidad + HR/asistencia + nómina + inventarios + compras (CxP) + ventas/POS (CxC) + payments + portfolio + reportes.

**Decisión abierta:** ¿una empresa o dos desde el día uno?
- **Una empresa:** más simple, arrancamos ya, el intercompany se prueba después.
- **Dos empresas:** activa de una vez el primitivo intercompany (finca cobra por cuenta del comisariato → CxP intercompañía). El código ya lo soporta.

> Pendiente de confirmar con Wis antes de armar el repo.

---

## 6. La línea que no se cruza: el net legal

En Nicaragua **la ley prohíbe descontar de la nómina** el crédito del comisariato o las deudas de préstamos. El trabajador recibe su **neto legal completo.** El cobro voluntario de deuda se maneja **aparte**, vía el kernel de portfolio, **después** de que cierra la planilla.

Esto **ya está blindado en el código de v2** (hay hasta un comentario `PROHIBIDO cobrar por la nómina`, y los campos de descuento de comisariato/préstamo quedan inertes). **v3 lo respeta igual, sin excepción.** No es una convención — es ley, y está enforced.

El complemento de salario se paga al trabajador pero **se excluye de la base de INSS** (invariante documentado, `net = gross`, separado de la planilla legal). v3 lo replica y deja la exposición visible en campos informativos.

---

## 7. Estrategia de testeo: módulo por módulo

**No se mete todo de un solo.** Se construye y se prueba una pieza, se valida que cierre limpio, y recién ahí se mete la siguiente. Así salen a la luz los bugs de integración y las inconsistencias **antes** de acumularse.

Orden de activación, siguiendo el flujo real de una empresa (cada pieza se apoya en la anterior):

1. **Estructura organizacional** — holding, empresa, sucursales, departamentos
2. **Catálogo de cuentas / contabilidad base** — CoA, períodos fiscales, tipo de cambio
3. **Empleados / HR + asistencia** — la gente y su fichaje
4. **Nómina** — se apoya en HR + contabilidad
5. **Inventarios** — qué hay para comprar y vender
6. **Proveedores + compras (CxP)** — entra mercadería, se debe pagar
7. **Clientes + ventas / POS (CxC)** — sale mercadería, se cobra
8. **Caja / arqueo** — apertura y cierre que cuadran
9. **Payments** — se cierran cobros y pagos
10. **Portfolio + reportes** — cartera viva y visibilidad de todo

### Qué cuenta como "pasó la prueba"

Un módulo **no** pasa solo porque el código corra. Pasa cuando cumple **todo** esto:

- [ ] Un usuario del campo lo completa **sin que nadie le explique**
- [ ] El flujo es lineal: paso 1 → 2 → 3 → listo
- [ ] Los mensajes son claros en español (nada de códigos de error crudos)
- [ ] Las validaciones **guían** (dicen qué falta), no rechazan en seco
- [ ] La operación **cierra limpio en contabilidad** (sin descuadres)
- [ ] **No genera inconsistencias** con los módulos ya probados antes
- [ ] Anda bien en tablet/móvil

---

## 8. Lo que NO hacemos

- **No reinventamos la rueda.** Es una empresa normal y corriente. Compra, vende, paga gente.
- **No arrastramos los bugs de integración de v2.** Por eso es repo nuevo, limpio.
- **No metemos complejidad.** Si una pantalla se siente complicada para el usuario del campo, está mal — se simplifica.
- **No tocamos v2.** Queda de referencia, intacto y ordenado.

---

## 9. El arranque del sistema (cómo se levanta todo)

El sistema **se crea uno por uno, a mano** — no con datos de prueba automáticos. La razón: creando cada cosa manualmente vamos **viendo los errores que aparecen y los arreglamos de una**, en el momento. Si metemos todo de golpe con un seed, los errores se esconden.

Hay **tres cosas distintas** que no hay que confundir:

- **El usuario del sistema** — el que entra con clave a manejar el programa.
- **La empresa** — la que compra, vende y paga.
- **Los trabajadores** — la gente que asiste y cobra nómina.

El arranque funciona así:

1. El sistema levanta un **usuario administrador temporal** — existe **solo para el primer ingreso**.
2. Ese admin entra y **crea la empresa** (nombre, datos, moneda).
3. El admin **se crea a sí mismo como empleado-administrador** dentro de la empresa (para quedar registrado en nómina y asistencia).
4. De ahí en adelante, **ese empleado-administrador es el que crea a los demás trabajadores**.
5. El **usuario admin temporal ya no se necesita**: se desactiva o se borra.

> Así la cadena queda limpia: **los empleados crean empleados**, y no quedan usuarios sueltos flotando sin estar ligados a una persona real. El admin temporal es un puente, no algo permanente.

Y una vez arrancado, el **orden de creación es el mismo flujo de una empresa normal**: estructura → cuentas → primer trabajador → segundo trabajador (para ver que no choquen entre ellos) → primera nómina → primera compra → primera venta → cierre. **Cada paso se valida antes de pasar al siguiente.**

---

## 10. Próximos pasos

1. **Confirmar:** ¿una empresa o dos para el demo? (define si el intercompany entra desde el inicio)
2. ✅ **Repo `ERP_v3` creado** — falta meter este documento en la raíz como norte.
3. **Definir el layout base** de v3 (reusando los kernels de v2, limpio).
4. **Arrancar por el paso 1** del orden de testeo (estructura organizacional) y no avanzar hasta que pase todos los criterios de §7.

---

*Este documento es la fuente de verdad de v3. Si algo en el código contradice esto, primero se discute y se actualiza acá.*
