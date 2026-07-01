# ROADMAP — ERP_v3

Estado de construcción, paso por paso. Manda el orden del `CLAUDE.md` / `ARQUITECTURA_V3.md`.

> **Regla:** no se avanza al siguiente paso hasta que el actual **pase la prueba del usuario del campo** y tenga sus bugs arreglados (ver `BUGS.md`).

## Estados

- **TODO** — no empezado
- **DOING** — en construcción / prueba
- **DONE** — pasó todos los criterios de abajo y cerró limpio
- **BLOCKED** — trabado por una dependencia o un bug abierto (anotar cuál en Notas)

## Criterios para marcar DONE (los 7, todos)

- [ ] Un usuario del campo lo completa **sin que nadie le explique**
- [ ] Flujo lineal: paso 1 → 2 → 3 → listo
- [ ] Mensajes claros en español (nada de códigos de error crudos)
- [ ] Validaciones que **guían** (dicen qué falta), no rechazan en seco
- [ ] Cierra **limpio en contabilidad** (sin descuadres)
- [ ] No genera inconsistencias con módulos ya probados
- [ ] Anda bien en tablet / móvil

## Alcance del demo

**UNA sola empresa.** Módulos encendidos: contabilidad, HR, nómina, inventario, compras, ventas/POS, payments, portfolio.
El resto (fleet, beneficio, estación de servicios, financiamiento, etc.) queda **apagado — no se borra, no se enciende.**

## Pasos de construcción

| #  | Paso                                                        | Estado | Notas |
|----|-------------------------------------------------------------|--------|-------|
| 1  | Estructura organizacional (holding → empresa → sucursal)    | DONE   | Verificado E2E por la UI real · BUG-001 cerrado · ver bitácora ↓ |
| 2  | Contabilidad base (CoA, período fiscal, tipo de cambio)     | TODO   |       |
| 3  | HR + asistencia (empleados y fichaje)                       | TODO   |       |
| 4  | Nómina (se apoya en HR + contabilidad)                      | TODO   |       |
| 5  | Inventarios                                                 | TODO   |       |
| 6  | Compras / CxP (proveedores, entrada de mercadería)          | TODO   |       |
| 7  | Ventas / POS / CxC (clientes, caja, crédito)                | TODO   |       |
| 8  | Caja / arqueo (apertura y cierre que cuadran)               | TODO   |       |
| 9  | Payments (cierra cobros y pagos)                            | TODO   |       |
| 10 | Portfolio + reportes (cartera viva y visibilidad)           | TODO   |       |

*Al empezar un paso, pasarlo a DOING; al cerrar limpio, a DONE.*

---

## Bitácora

### Paso 1 — Estructura organizacional · DONE (2026-07-01)

- **Entorno v3 levantado con DB vacía** (docker: `db + backend + frontend`). El copiado de v3 estaba incompleto: se trajo `requirements/` de v2 y se creó el `.env` de raíz. `dash_analytics` no se levanta (no hace falta).
- **Empresa creada a mano por el wizard real** (no seed): Holding **Agrícola Santa Isabel** → Empresa **Comisariato Santa Isabel** (RUC J0310000012345) → Sucursal **Casa Matriz**. Moneda **NIO (C$)** confirmada en el tablero.
- **BUG-001 encontrado y cerrado**: el admin rebotaba a `/login` tras el wizard (estado `is_fresh` cacheado). Fix en `frontend/src/stores/auth.store.ts`. Re-verificado E2E: ahora entra directo al tablero.
- **BUG-002 abierto** (media): el admin del bootstrap es superusuario permanente, no "temporal que se desactiva" — a resolver en el paso 3 (HR/empleado-administrador).
- **Los 7 criterios del usuario del campo: verificados** (flujo lineal, español claro, validaciones que guían, cierra limpio, sin inconsistencias, responsive tablet/móvil).
- **Módulos:** los verticales (fleet, beneficio, financiamiento, fuel, cec, comisariato, finca) quedan OFF por default — la regla "el resto apagado" se cumple sola.

**Pendiente global (no bloquea):** push de la baseline a GitHub, bloqueado hasta que el repo v3 sea **privado**.
