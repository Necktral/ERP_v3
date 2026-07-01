# GUÍA MAESTRA — Construcción de ERP_v3 paso a paso

**Agrícola Santa Isabel** · Este archivo es el **caminito**: la línea de trabajo enfocada para construir v3 sin perderse y sin desviarse. Claude Code lo lee y lo sigue. Junto con `CLAUDE.md` (la constitución) y `ARQUITECTURA_V3.md` (el norte), manda sobre el trabajo.

> **Regla de uso:** se avanza **un paso a la vez, en orden.** No se pasa al siguiente paso hasta que el actual cumpla los 7 criterios del usuario del campo (ver abajo) y se muestre a Wis para su visto bueno. Lento pero seguro.

---

## Reglas transversales (mandan en TODOS los pasos)

1. **Simplicidad para el usuario del campo.** Gente del campo, uso limitado de computadora. Cada flujo: lineal (paso 1 → 2 → 3 → listo), mínimos clics, mensajes claros en español (no códigos de error), validaciones que guían, apoyo visual, responsive (tablet/móvil).

2. **El neto legal de nómina es inviolable.** No se descuenta comisariato ni deudas de la planilla. El trabajador recibe su neto legal completo. El cobro de deuda va aparte, vía portfolio, **después** de la planilla. Ya está enforced en el código — no se toca.

3. **Base de datos vacía, creación manual.** Todo se crea **a mano, por la interfaz real** — NO con seeds. Los seeds (`seed_dev_environment`) son solo taller del desarrollador, nunca lo que se prueba ni lo que se demuestra. Crear uno por uno es lo que hace salir los bugs a la luz.

4. **v2 es referencia, no se toca.** Vive en `../ERP_v2`. Se consulta para ver cómo se resolvió algo; nunca se le hace commit ni se construye ahí.

5. **Activación selectiva de módulos.** La empresa prende solo lo que necesita. Los módulos que no se usan quedan apagados (no se borran — rompen dependencias). Ver la sección "Estado de módulos".

6. **Árbitro de desvíos.** Si aparece una tarea que no es del paso actual, se declara **fuera de scope** y se difiere al paso que corresponda (o se anota en `BUGS.md`). Nada de irse a construir OAuth/MCP/features de v2 en medio del arranque. El ROADMAP manda.

---

## Los 7 criterios de "pasó la prueba del usuario del campo"

Un paso NO está terminado por que el código corra. Está terminado cuando cumple **todo** esto:

- [ ] Un usuario del campo lo completa **sin que nadie le explique**
- [ ] El flujo es lineal (paso 1 → 2 → 3 → listo)
- [ ] Los mensajes son claros en español (nada de códigos de error crudos)
- [ ] Las validaciones **guían** (dicen qué falta), no rechazan en seco
- [ ] La operación **cierra limpio en contabilidad** (sin descuadres)
- [ ] **No genera inconsistencias** con los pasos ya validados
- [ ] Anda bien en tablet/móvil

---

## Estado actual (dónde estamos hoy)

- **Base firme y coherente:** v2 copiado entero, DB limpia, 239 tablas, 218 migraciones, `manage.py check` sin problemas y sin drift de migraciones. No es un esqueleto.
- **Empresa creada a mano (paso 1 DONE):** Holding **Agrícola Santa Isabel** (id 1) → Empresa **Comisariato Santa Isabel** (id 2, RUC J0310000012345) → Sucursal **Casa Matriz** (id 3). Admin creado y logueado. Moneda NIO.
- **1 empresa, 1 usuario, 0 datos operativos** — correcto, por el arranque manual.

---

## Huecos conocidos y bugs abiertos

- **BUG-002 (media, diferido a Paso 3):** el admin del bootstrap es superusuario permanente, no el "admin temporal que se desactiva" de la constitución. Se resuelve cuando entre el empleado-administrador en HR.
- **BUG-003 — CERRADO (2026-07-01):** el `qa/` de la raíz de v2 (guards de QA) no se había copiado a v3. Carpeta repuesta; los 6 tests guard que fallaban ahora pasan. Ver `BUGS.md`.
- **Baseline protegida (2026-07-01):** commit local de todo v3 hecho. El **push a GitHub sigue pendiente** hasta que el repo sea privado — se decide aparte.
- **Brecha de módulos del demo:** de los módulos que el demo necesita, hay **5 apagados por default** → `inventory`, `procurement`, `pos`, `payments`, `portfolio`. Se encienden en su paso correspondiente (ver cada paso abajo). No es bug; es parte del plan.

---

## Estado de módulos (qué está prendido y qué hay que encender)

**Encendidos por default hoy (16), no hay que tocar:**
organization, human_resources, accounting, audit, synchronization, parties, payroll, billing, reporting, controls, analytics, alertas, chatter, documents, knowledge, diagnostics.

**Apagados que el demo necesita → se encienden en su paso, por empresa** (con el servicio de activación de módulos, `set_company_modules`, que ya está implementado y auditado):

| Módulo | Se enciende en |
|---|---|
| `inventory` | Paso 5 |
| `procurement` (compras) | Paso 6 |
| `pos` (y verificar si `comisariato`/`retail_pos` hacen falta para las pantallas usadas) | Paso 7 |
| `payments` | Paso 8–9 |
| `portfolio` | Paso 10 |

**Quedan apagados todo el demo** (no se usan): fuel, cec, finca, fleet, financiamiento, beneficio.

---

## LOS 10 PASOS

Los modelos ya existen (v3 = copia de v2). Cada paso es **crear por la interfaz y probar**, no programar de cero.

### Paso 1 — Estructura organizacional → DONE
Holding → empresa → sucursal, creados a mano. Admin logueado. BUG-001 (login rebotaba) cazado y arreglado. Validado E2E por UI.

### Paso 2 — Contabilidad base
- **Módulos:** `accounting` ya está ON. Nada que encender.
- **Crear a mano:** Catálogo de cuentas mínimo funcional (NIO, posteable): Caja (1101), CxC (1201), Inventario (1301), CxP (2101), Nómina por pagar (2201), Impuestos por pagar (2301), Ventas (4101), Devoluciones (4201), Costo de ventas (5101), Nómina (5201). Configurar **tipo de cambio** USD→NIO (36.6243) del período.
- **Aclaración v3 sobre el período fiscal:** el período **no se "crea" por la UI** — nace **OPEN automáticamente** con el primer asiento posteado (diseño del kernel accounting). En este paso solo se verifica que la pantalla de períodos carga y se entiende; el período del mes quedará OPEN con el primer posteo real (nómina, Paso 4).
- **Efecto esperado:** la config contable de la empresa queda lista; sin asientos todavía.
- **NO hacer:** no cargar movimientos ni asientos aún; eso viene con compra/venta/nómina.

### Paso 3 — HR + Asistencia
- **Módulos:** `human_resources` ya ON.
- **Crear a mano:** el **empleado-administrador** (el que el admin se crea a sí mismo). Luego un par de empleados de prueba (cédula, INSS o en blanco si no tiene, salario, tipo de salario, régimen INSS). Registrar asistencia de un período (días trabajados).
- **Resolver aquí BUG-002:** desactivar/despermanentizar el admin temporal una vez que exista el empleado-administrador.
- **Efecto esperado:** empleados en el sistema, asistencia lista para alimentar la nómina.
- **NO hacer:** no correr la planilla todavía (es el paso 4).

### Paso 4 — Nómina
- **Módulos:** `payroll` ya ON.
- **Crear a mano:** un **período de nómina** (quincena/catorcena), y la **planilla** con los empleados del paso 3. Verificar el cálculo (INSS laboral, IR por brackets Ley 822, neto legal, patronal) contra una calculadora o el Excel de referencia.
- **Verificar el invariante:** que NO haya descuentos de comisariato ni préstamos en la planilla. El neto es el legal completo.
- **Efecto esperado:** al postear, genera asientos (Nómina 5201 al Debe; Nómina por pagar 2201, Impuestos por pagar 2301 al Haber; luego pago contra Caja 1101).
- **NO hacer:** no meter cobro de deuda por la nómina — eso es portfolio, paso 10.

### Paso 5 — Inventarios
- **Módulos:** **ENCENDER `inventory`** para la empresa.
- **Crear a mano:** un almacén, y productos (ej. Café verde, código, precio de costo, stock inicial 0).
- **Efecto esperado:** catálogo de productos listo, stock en cero, listo para recibir compras.
- **NO hacer:** no registrar compras ni ventas todavía (pasos 6 y 7).

### Paso 6 — Compras / CxP
- **Módulos:** **ENCENDER `procurement`.**
- **Crear a mano:** un **proveedor** (parties), y una **entrada a inventario** (compra): cantidad, precio unitario, total. Genera CxP.
- **Efecto esperado:** stock sube; asiento Inventario (1301) al Debe, CxP (2101) al Haber; la CxP aparece en cartera.
- **NO hacer:** no pagar la CxP todavía (paso 9).

### Paso 7 — Ventas / POS / CxC
- **Módulos:** **ENCENDER `pos`.** Verificar contra la UI si `comisariato` o `retail_pos` hacen falta para las pantallas de venta que se usan; encender lo que el flujo real requiera.
- **Crear a mano:** un **cliente** (parties), y una **venta** por POS: producto, cantidad, precio, forma de pago (crédito → CxC; contado → caja). Escanear producto si aplica.
- **Efecto esperado:** stock baja; asiento CxC (1201) o Caja (1101) al Debe, Ventas (4101) al Haber; Costo de ventas (5101) al Debe, Inventario (1301) al Haber. Sin descuadres.
- **NO hacer:** no meter todavía cierre de caja ni cobros (pasos 8 y 9).

### Paso 8 — Caja / Arqueo
- **Módulos:** `payments` (encender aquí si no se hizo).
- **Crear a mano:** **arqueo de apertura** (dinero inicial) y, tras las ventas de contado, **arqueo de cierre** por denominación. El dinero físico tiene que cuadrar con el sistema.
- **Efecto esperado:** el arqueo cuadra; si no, hay que investigar el flujo de caja (posible bug).
- **NO hacer:** no dar por bueno un arqueo descuadrado sin investigar.

### Paso 9 — Payments (cobros y pagos)
- **Módulos:** `payments` ON.
- **Crear a mano:** **cobrar** la CxC del cliente (paso 7) y **pagar** la CxP del proveedor (paso 6).
- **Efecto esperado:** Caja sube con el cobro (Debe Caja / Haber CxC); baja con el pago (Debe CxP / Haber Caja). Saldo de caja consistente.
- **NO hacer:** —

### Paso 10 — Portfolio + Reportes
- **Módulos:** **ENCENDER `portfolio`.** `reporting` ya ON.
- **Verificar:** la cartera viva (CxC/CxP) cierra sin inconsistencias. Aquí es donde el **cobro voluntario de deuda del comisariato** se maneja (separado de la nómina). Estado de Resultados y Balance General cuadran (Activos = Pasivos + Patrimonio).
- **Efecto esperado:** visibilidad integrada; el balance cierra.
- **NO hacer:** —

---

## HITO FINAL — Las dos empresas cruzadas (después del paso 10)

Este es el 25% que Wis quiere probar: dos empresas con cruce real.

- **Crear Empresa 2** (la que tiene trabajadores que sacan crédito del POS del comisariato de Empresa 1).
- **ENCENDER `intercompany`** y verificar la autorización entre empresas (CompanyLink + grant).
- **Flujo del cruce:** Empresa 1 (comisariato) le da crédito a trabajadores de Empresa 2 → se registra el intercompany: **CxC en Empresa 1, CxP en Empresa 2**, y la consolidación lo elimina. Sin duplicación.
- **Verificar:** nómina de **ambas** empresas (neto legal en las dos), CxC/CxP de cada una, y el estado consolidado de grupo (quién debe qué a quién).
- **Recordatorio:** el crédito del comisariato **nunca** se descuenta de la nómina — se cobra por portfolio/intercompany, aparte.

---

## Glosario rápido

- **Kernel:** bloque reutilizable probado (accounting, nomina, inventarios, facturacion, payments, portfolio, reporting).
- **Neto legal:** lo que el trabajador recibe por ley; inviolable, no admite descuentos de comisariato/préstamos.
- **CxC / CxP:** cuentas por cobrar / por pagar.
- **Intercompany:** cuando una empresa cobra o paga por cuenta de otra; genera CxC en una y CxP en la otra, y se elimina en la consolidación.
- **Arqueo:** conteo del dinero físico de caja vs. lo que dice el sistema; tiene que cuadrar.
- **Override de módulo:** encender/apagar un módulo para una empresa específica, sobre el default del catálogo.

---

*Fuente de verdad operativa de v3. Si el código o una decisión contradice esto, primero se discute y se actualiza acá.*
