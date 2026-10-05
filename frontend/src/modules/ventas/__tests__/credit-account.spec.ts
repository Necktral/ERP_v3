import { describe, expect, it } from 'vitest';
import { isCreditAccountNotFound } from 'src/modules/ventas/api';

describe('clasificación de errores de cuenta de crédito', () => {
  it('traduce únicamente 404 a cliente sin cuenta', () => {
    expect(isCreditAccountNotFound({ response: { status: 404 } })).toBe(true);
  });

  it.each([401, 403, 500])('no oculta el error HTTP %s', (status) => {
    expect(isCreditAccountNotFound({ response: { status } })).toBe(false);
  });

  it('no oculta errores de red', () => {
    expect(isCreditAccountNotFound(new Error('Network Error'))).toBe(false);
  });
});
