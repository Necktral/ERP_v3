# Contraste normativo Nicaragua — corte 2026-08-18

## Alcance y condición de cierre

Este documento contrasta parámetros implementados con fuentes estatales disponibles. Es una
verificación técnica, no una opinión legal ni contable. El cierre de cumplimiento requiere firma
de Wis y revisión de un contador/abogado nicaragüense, especialmente para los puntos `LEGAL-PEND`.
Las fuentes primarias enlazadas se volvieron a consultar el 2026-08-18; no se encontró una
resolución MITRAB/Gaceta 2026 firmada que permita cerrar `LEGAL-PEND-003`.

## Fuentes primarias consultadas

- [Código del Trabajo, Ley 185 — Asamblea Nacional](https://legislacion.asamblea.gob.ni/Normaweb.nsf/%28%24All%29/FA251B3C54F5BAEF062571C40055736C)
- [Ley de Concertación Tributaria, Ley 822 — Asamblea Nacional](https://legislacion.asamblea.gob.ni/Diariodebate.nsf/76ed72912dd57e570625698c00773f5d/29db3f80f66e1f5706257b5900630b21)
- [Ley 1279, reforma de la Ley 822, Gaceta 61 del 09-04-2026](https://www.spiex.gob.ni/media/4mpnovbp/2026-04-09-ley-1279-ley-de-reformas-y-derogacio-n-a-la-ley-822.pdf)
- [Regímenes de afiliación y tasas — INSS](https://inss-princ.inss.gob.ni/index.php/tramites-37/10-afiliaciones/13-regimenes-de-afiliacion)
- [Ley de Salario Mínimo, Ley 625 — Asamblea Nacional](https://legislacion.asamblea.gob.ni/Normaweb.nsf/%28%24All%29/D4A4AB6A3935BB7906257331005B6D2C)

## Matriz de contraste

| Materia | Norma observada | Implementación | Veredicto técnico |
|---|---|---|---|
| IR de rentas del trabajo | Ley 822, arts. 21 y 23: cotización social deducible y tramos anuales 0–100k, 15%, 20%, 25%, 30% | `NICARAGUA_2026_IR_BRACKETS` reproduce límites, bases y tasas; el cálculo resta INSS laboral antes de anualizar | COINCIDE. La Ley 1279 de abril de 2026 reforma otros artículos, no 19/21/23; ésta es una inferencia jurídica que requiere visto bueno. |
| INSS laboral/patronal | INSS publica 7% laboral y 21.5%/22.5% patronal según tamaño | Defaults 7%, 21.5%, 22.5%, configurables por empresa/vigencia | COINCIDE en tasas. Ver `LEGAL-PEND-002` para exactamente 50 empleados. |
| Vacaciones | Código del Trabajo, arts. 76–79: 15 días por cada 6 meses, pago según último salario ordinario/promedio variable | Provisión 8.3333% y ledger HR mensual configurable | COINCIDE aritméticamente; falta golden legal del promedio variable y terminación laboral. |
| Décimo tercer mes | Arts. 93–97: un mes/proporcional, reglas de salario variable, fecha de pago y exención de descuentos/cotizaciones | Provisión 8.3333%; la planilla ordinaria no grava la provisión | PARCIAL: provisión coincide; falta certificar pago, mora, salario variable y liquidación con golden oficial. |
| Jornada/descanso/feriados | Arts. 50–69: límites diurno/nocturno, séptimo día y remuneración extraordinaria | Tasas configurables para extra, domingo, séptimo y feriado | PARCIAL: tasas base existen; falta matriz legal por jornada diurna/nocturna/mixta y coincidencia de calendarios. |
| Salario mínimo | Ley 625 exige tabla sectorial vigente y reajuste periódico | Sólo existe default agropecuario 2026 `C$6,188.02`, configurable | PARCIAL: el monto coincide con el acuerdo público reportado, pero falta archivar la resolución MITRAB/Gaceta firmada como fuente primaria y modelar los demás sectores. |

## Pendientes que requieren criterio profesional

- **LEGAL-PEND-001 — “Complemento” salarial fuera de INSS/IR.**
  `services_complement.py` declara `net = gross` y excluye siempre el complemento de la base legal.
  La Ley 822 grava rentas del trabajo y el Código define ampliamente el salario ordinario. Antes de
  usar este carril en producción, un profesional debe determinar si cada concepto es realmente no
  salarial/exento y documentar su fundamento. Recomendación técnica: catálogo de conceptos con
  tratamiento legal versionado; no una exclusión global.
- **LEGAL-PEND-002 — Umbral patronal con exactamente 50 trabajadores.**
  La página INSS resume “menos de 50” y “más de 50”; el código aplica 22.5% desde `>= 50`. Obtener el
  decreto/resolución aplicable y confirmar el caso frontera antes de firmar la configuración.
- **LEGAL-PEND-003 — Tabla oficial de salario mínimo 2026.**
  Incorporar al expediente la resolución firmada de la Comisión/MITRAB o su publicación en Gaceta,
  con vigencia y obligación de alimentación del sector agropecuario.
- **LEGAL-PEND-004 — Golden legales.**
  Wis/contador debe suministrar recibos esperados para mensual, quincenal, catorcenal, salario
  variable, vacaciones, aguinaldo, subsidio, terminación y cambio de tasa dentro del año.

## Visto bueno

- Wis (operación): **PENDIENTE**
- Contador autorizado: **PENDIENTE**
- Abogado laboral/tributario: **PENDIENTE**
