# Handoff de gobierno — auditoría forense ERP_v3

> Estado del documento: **preparación de cierre**. Este handoff no certifica todavía la suite
> backend completa, los gates finales, las migraciones, el preflight productivo ni el cierre de
> U23–U30/L4–L5. Esas decisiones requieren evidencia fresca del HEAD integrado.

## Diagnóstico del área

La campaña recuperó una auditoría que había sido declarada terminada antes de cumplir sus gates.
El trabajo válido se preservó y se reforzaron los controles de aislamiento tenant, concurrencia,
dinero, autenticación, frontend y operación. A fecha de este handoff existe evidencia dirigida para
U1–U22 y L1–L3, pero el cierre global continúa condicionado a la corrida agregada final.

## Alcance exacto

- Rama/worktree local `audit/forense-integral-2026-08`; sin push.
- Backend, frontend, contratos QA y evidencia reproducible del ERP_v3.
- PostgreSQL y servicios del proyecto Docker `erpv3_forensic`; la DB demo permanece fuera de alcance.
- Este corte documental abarca U1–U22 y L1–L3. No modifica ni prejuzga U23–U30/L4–L5.
- Cumplimiento legal/contable permanece separado del cierre técnico y requiere visto bueno humano.

## Contratos impactados

- Aislamiento por `company + branch` y RBAC efectivo en endpoints de negocio.
- Idempotencia y serialización de refresh, bootstrap, 2FA, pagos, caja, inventario, nómina,
  reporting, posteo, compras y numeración fiscal.
- Contratos frontend/API de rutas, paginación, asistencia de campo y errores normalizados.
- Contratos operativos de POS edge: firma, challenge de un uso, replay y kill-switch.
- Contratos de cierre forense: reportes frescos, matrices 30U/5L, riesgos residuales y worktree limpio.

## Pruebas / validación

Evidencia dirigida disponible a este corte:

- L1: guard RBAC fresco con 306 escrituras, 292 gateadas y exactamente 14 excepciones
  credencializadas; matriz adversarial 16/16.
- L2: matriz PostgreSQL real 21/21 para refresh/bootstrap/2FA, POS, inventario, caja,
  conciliación, nómina, token reporting, posteo, compras y fiscal.
- L3/U13: integrador dirigido 15/15, con regresiones de BUG-057/058.
- U15: lectura persistida tenant-scoped de rollcall, cuadrillas y solicitudes SoD; backend 2/2,
  frontend 2/2 y typecheck dirigido verde.
- U19: edge HTTP `passed` (firma válida, replay 409, firma inválida 401), pilot smoke `passed` y
  rollback `passed`, con kill-switch 403; trazas con secretos redactados.

Estas corridas son evidencia de dominio. **No sustituyen** la suite backend/frontend completa ni
los gates agregados finales del commit integrado.

## Riesgos remanentes

- U23–U30/L4–L5 no se evalúan en este corte documental.
- Falta ejecutar y fijar el manifest final contra el commit integrado y un worktree limpio.
- Falta confirmar suite backend completa, frontend lint/typecheck/Vitest/build, migraciones desde
  cero, smoke/E2E por rol, accesibilidad, offline/reconexión y preflight productivo.
- El visto bueno fiscal, laboral, contable y legal corresponde a Wis y profesionales autorizados.

## Blast radius / radio de impacto

Los cambios atraviesan autenticación, IAM/RBAC, kernels financieros, módulos operativos, frontend y
QA. El principal riesgo de integración es una regresión cross-kernel o que un reporte verde haya
sido generado contra un commit anterior. Por eso el cierre exige manifest con commit/fecha,
reportes frescos y un único gate agregador bloqueante.

## Plan de rollback

- No se hará push durante la auditoría.
- Los cambios están separados en commits locales por dominio y pueden revertirse atómicamente.
- Las migraciones requieren ensayo expansión → backfill → constraint; el retiro irreversible del
  token biométrico plaintext se documenta como rollback fail-safe, no como restauración del secreto.
- Ante un gate rojo se conserva evidencia, se revierte sólo el cambio causal y se repite la suite
  dirigida antes de la regresión agregada.

## Estado de gates

Estado provisional, sin declaración final:

- Evidencia dirigida U1–U22/L1–L3: disponible según `docs/AUDITORIA_LOG.md`.
- POS edge/pilot: reportes frescos `passed`.
- Gate agregador, suite completa, migraciones, preflight y worktree limpio: **pendientes de la
  corrida final integrada**.

## Estado de excepciones de seguridad

El guard fresco encontró exactamente las 14 excepciones versionadas, cero nuevas y cero obsoletas.
Cada excepción usa una credencial alternativa (estado bootstrap, credenciales de cuenta, refresh,
challenge 2FA, token embed, enrolamiento, firma de dispositivo o token biométrico). La matriz
negativa verifica fail-closed sin esa credencial. Este resultado deberá incorporarse al manifest
final antes de certificar el cierre.

## Incidente de entrega prematura

La entrega anterior fue prematura por una falla de control de cierre, no porque todos los criterios
hubieran sido satisfechos:

- Se tomaron mensajes de agentes que decían “completado” para lotes concretos como señal de cierre general.
- No se ejecutó una auditoría final del worktree antes de entregar: quedaron 17 archivos modificados y 11 sin seguimiento.
- Se conservaron reportes fallidos: backend con 2 fallos, gobernanza fallida y OpenAPI fallido.
- `BUG-002`, `BUG-049`, unidades, lentes, E2E y vistos buenos seguían pendientes.
- Faltó un único gate agregador que exigiera worktree limpio, cero bugs abiertos, matrices cerradas y reportes frescos.
- Se añadió un gate de cierre y una lista de comprobación firmada para impedir otra declaración prematura.

Medida preventiva: ningún resultado parcial ni mensaje de agente equivale a cierre. La declaración
final sólo puede emitirse después de que el gate agregador valide simultáneamente el manifest del
HEAD, reportes frescos, JUnit sin fallos, 30U/5L cerradas, riesgos residuales, preflight/migraciones,
evidencia browser/E2E y `git status` limpio.
