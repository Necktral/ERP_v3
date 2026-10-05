# AGENTS.md — Contexto y reglas de trabajo para ERP_v3

Este archivo lo lee Codex al inicio de cada sesión. Es la constitución del proyecto. **Léelo completo antes de tocar nada.**

---

## Qué es este proyecto

**ERP_v3** — reconstrucción limpia y testeada de un ERP/CRM para **Agrícola Santa Isabel** (holding cafetalero, Jinotega, Nicaragua).

El norte completo del proyecto está en **`ARQUITECTURA_V3.md`** (en esta misma carpeta). Ese documento manda. Si algo acá contradice ese documento, gana el documento y se avisa.

---

## La relación con ERP_v2 (referencia)

- **`ERP_v2`** vive en `../ERP_v2` (carpeta hermana). Es el sistema anterior: **funciona en código**, pero tiene bugs de UX e inconsistencias en uso real.
- **ERP_v2 es SOLO REFERENCIA. NO se toca, no se modifica, no se le hace commit.** Es el blueprint del que sacamos lo que ya está probado.
- **ERP_v3 es donde se construye.** Es un *copy-paste inteligente* de v2: se reusa lo que funciona, pero organizado, limpio y **testeado pieza por pieza**.

Cuando necesites ver cómo se resolvió algo en v2 (un modelo, un servicio, un cálculo), **consultá `../ERP_v2`** — pero nunca escribas ahí.

---

## Aclaraciones que mandan (v3.1 — no son contradicciones)

Tres precisiones que resuelven confusiones frecuentes. Léelas como parte de la constitución:

- **El seed es solo taller del desarrollador.** *seed_dev_environment es SOLO banco de trabajo del desarrollador — datos scratch para programar contra algo. Lo que se PRUEBA y lo que se MUESTRA a los stakeholders siempre se crea manual, paso a paso. Un entorno seedeado nunca es la base que se valida ni lo que se demuestra.*

- **v2 es hermana, no contenedora.** *ERP_v2 es carpeta hermana de referencia (`../ERP_v2`), no contenedora.*

- **v3 arranca como copia fiel de v2, y eso está bien.** *v3 arranca como copia fiel del código de v2. La limpieza viene de: base de datos vacía + activación selectiva de módulos por empresa + arreglo de bugs módulo por módulo conforme se validan. Los módulos no usados no se borran, solo no se encienden.*

---

## Los kernels: se reusan tal cual, todos

Los 7 kernels de v2 son **bloques de confianza ya verificados**. No se reinventan. Se reusan:

1. **accounting** — doble partida event-sourced (EconomicEvent → JournalDraft → JournalEntry), períodos fiscales, reglas de posteo versionadas, multimoneda, consolidación.
2. **nomina** — cálculo legal nicaragüense (Ley 822, art. 21 LCT), INSS/IR, patronal, séptimo día. Incluye biométrico y asistencia de campo.
3. **inventarios** — stock, costos, movimientos.
4. **facturacion** — facturas y documentos de venta.
5. **payments** — cobros y pagos.
6. **portfolio** — cartera: CxC, CxP, deudas, créditos.
7. **reporting** — visibilidad integrada.

Primitivos ya construidos en v2 que también se reusan: **intercompany** (cruce entre empresas), **régimen INSS fechado**, **arqueo de caja por denominación**, **POS offline-first**, **seed_dev_environment**.

---

## Reglas de oro (NO negociables)

1. **Simplicidad para el usuario del campo.** La gente que usa esto vive en el campo y tiene uso limitado de computadora. Todo tiene que ser: flujos lineales (paso 1 → 2 → 3 → listo), mínimos clics, mensajes claros en español (no códigos de error), validaciones que guían en vez de rechazar en seco, apoyo visual (iconos/colores/estados), y que ande en tablet. **Si un cajero del campo no puede completar la tarea sin que le expliquen, la tarea NO está terminada — aunque el código funcione.**

2. **El net legal es inviolable.** En Nicaragua la ley prohíbe descontar de la nómina el crédito del comisariato o deudas. El trabajador recibe su **neto legal completo**. El cobro de deuda se maneja **aparte, vía portfolio, DESPUÉS de que cierra la planilla.** Ya está enforced en v2 — se respeta igual.

3. **Se construye y se prueba pieza por pieza.** No se mete todo de golpe. Una pieza, se valida que cierre limpio, y recién ahí la siguiente. Así los errores salen a la luz temprano.

4. **Draft-first para lo crítico.** Nada escribe directo a tablas críticas sin revisión humana.

---

## Cómo se levanta el sistema (arranque)

Se crea **uno por uno, a mano** — no con seeds masivos — para cazar los errores en el momento.

Tres cosas distintas que NO se confunden: **usuario del sistema** (entra con clave), **empresa** (compra/vende/paga), **trabajadores** (asisten y cobran).

Flujo de arranque:
1. El sistema levanta un **usuario admin temporal** (solo para el primer ingreso).
2. Ese admin **crea la empresa**.
3. El admin **se crea a sí mismo como empleado-administrador**.
4. De ahí, **ese empleado-administrador crea a los demás trabajadores**.
5. El **admin temporal se desactiva/borra** — ya no se necesita.

---

## Orden de construcción y testeo

Sigue el flujo de una empresa normal. Cada paso se valida antes de avanzar:

1. Estructura organizacional (holding → empresa → sucursal)
2. Catálogo de cuentas / contabilidad base (CoA, período fiscal, tipo de cambio)
3. Empleados / HR + asistencia
4. Nómina (se apoya en HR + contabilidad)
5. Inventarios
6. Proveedores + compras (genera CxP)
7. Clientes + ventas / POS (genera CxC)
8. Caja / arqueo (apertura y cierre que cuadran)
9. Payments (cierra cobros y pagos)
10. Portfolio + reportes

---

## Alcance del demo

- **Se arranca con UNA sola empresa.** Se prueba el ciclo completo (compra → venta → nómina → caja) limpio y simple.
- **La segunda empresa + el cruce intercompany se suman DESPUÉS**, como el siguiente hito, cuando la primera ya esté sólida.
- El objetivo es una **demostración para los stakeholders familiares** de Agrícola Santa Isabel: mostrar que el sistema funciona y está listo para uso operativo real.

---

## Lo que NO se hace

- No se reinventa la rueda. Es una empresa normal: compra, vende, paga gente.
- No se arrastran los bugs de integración de v2.
- No se mete complejidad. Si una pantalla se siente complicada para el usuario del campo, está mal.
- No se toca ERP_v2.

---

## Metodología con Codex

- Trabajá **solo dentro de `ERP_v3`**. Consultá `../ERP_v2` como referencia de lectura.
- Antes de construir un módulo, mirá cómo está resuelto en v2 y reusá el kernel correspondiente.
- Mantené un archivo **`ROADMAP.md`** con el estado (TODO / DOING / DONE / BLOCKED) de cada paso del orden de construcción.
- Cuando encuentres un bug durante el testeo, documentalo en **`BUGS.md`** (pasos para reproducir, esperado vs. actual, impacto) antes de arreglarlo.
- No incluyas explicaciones técnicas largas en las respuestas de chat a menos que se pidan — el usuario prefiere prosa clara y conceptual.
