import { describe, expect, it } from 'vitest';
import {
  hasRequiredModule,
  isAllowedInNativeShell,
  requiredModuleForPath,
} from 'src/router/access';

describe('route access', () => {
  it('resuelve el módulo por el prefijo más específico', () => {
    expect(requiredModuleForPath('/ventas')).toBe('pos');
    expect(requiredModuleForPath('/ventas/historial')).toBe('billing');
    expect(requiredModuleForPath('/contabilidad/diario')).toBe('accounting');
    expect(requiredModuleForPath('/tablero')).toBeNull();
  });

  it('bloquea una URL directa cuando el módulo está apagado', () => {
    expect(hasRequiredModule('/inventario/conteo', ['billing'])).toBe(false);
    expect(hasRequiredModule('/inventario/conteo', ['inventory'])).toBe(true);
  });

  it('limita el shell nativo a CO-PA y rutas de sesión', () => {
    expect(isAllowedInNativeShell('/nomina/sala-de-pago')).toBe(true);
    expect(isAllowedInNativeShell('/login/2fa')).toBe(true);
    expect(isAllowedInNativeShell('/tablero')).toBe(false);
    expect(isAllowedInNativeShell('/contabilidad')).toBe(false);
  });
});
