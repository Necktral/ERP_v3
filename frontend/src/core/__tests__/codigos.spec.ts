import { describe, expect, it } from 'vitest';

import { apiErrorMessage } from 'src/core/api';
import { CODIGOS, esCodigoBackend, traducirCodigo } from 'src/core/codigos';

/** Arma un error de axios con el payload dado. */
function errorCon(data: unknown) {
  return { response: { data } };
}

describe('codigos (diccionario central)', () => {
  it('traduce códigos conocidos y devuelve tal cual los desconocidos', () => {
    expect(traducirCodigo('SALES_INSUFFICIENT_STOCK')).toBe(CODIGOS.SALES_INSUFFICIENT_STOCK);
    expect(traducirCodigo('CODIGO_INVENTADO_XYZ')).toBe('CODIGO_INVENTADO_XYZ');
  });

  it('reconoce el formato CODIGO_EN_MAYUSCULAS', () => {
    expect(esCodigoBackend('SYNC_TIME_SKEW')).toBe(true);
    expect(esCodigoBackend('INVALID_AMOUNT')).toBe(true);
    expect(esCodigoBackend('No se pudo guardar')).toBe(false);
    expect(esCodigoBackend('detalle')).toBe(false);
  });
});

describe('apiErrorMessage + diccionario', () => {
  it('traduce un detail con código conocido', () => {
    const e = errorCon({ detail: 'SALES_NO_OPEN_CASH_SESSION' });
    expect(apiErrorMessage(e)).toBe(CODIGOS.SALES_NO_OPEN_CASH_SESSION);
  });

  it('deja intacto un detail sin formato de código', () => {
    const e = errorCon({ detail: 'No se pudo pagar un documento anulado' });
    expect(apiErrorMessage(e)).toBe('No se pudo pagar un documento anulado');
  });

  it('deja intacto un detail con código desconocido (fallback honesto)', () => {
    const e = errorCon({ detail: 'OTRO_CODIGO_RARO' });
    expect(apiErrorMessage(e)).toBe('OTRO_CODIGO_RARO');
  });

  it('traduce el envelope {error, message} de cartera (primer error de campo)', () => {
    const e = errorCon({ error: 'INVALID_AMOUNT', message: 'Amount must be positive' });
    expect(apiErrorMessage(e)).toBe(CODIGOS.INVALID_AMOUNT);
  });

  it('mantiene el formato "campo: mensaje" para errores de campo comunes', () => {
    const e = errorCon({ nombre: ['Este campo es requerido.'] });
    expect(apiErrorMessage(e)).toBe('nombre: Este campo es requerido.');
  });

  it('usa el fallback cuando no hay data', () => {
    expect(apiErrorMessage({}, 'Falló la carga.')).toBe('Falló la carga.');
  });

  it('normaliza envelopes anidados y estados HTTP', () => {
    expect(apiErrorMessage(errorCon({ error: { code: 'INVALID_AMOUNT', message: 'English' } }))).toBe(
      CODIGOS.INVALID_AMOUNT,
    );
    expect(apiErrorMessage({ response: { status: 403, data: {} } })).toBe(
      'No tenés permiso para realizar esta acción.',
    );
    expect(apiErrorMessage({ response: { status: 503, data: {} } })).toBe(
      'El servidor no pudo completar la operación.',
    );
  });
});
