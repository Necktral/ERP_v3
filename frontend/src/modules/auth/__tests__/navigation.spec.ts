import { describe, expect, it } from 'vitest';
import routes from 'src/router/routes';
import { AUTHENTICATED_HOME_ROUTE } from 'src/modules/auth/navigation';

describe('navegación posterior a autenticación', () => {
  it('usa la raíz canónica y esa ruta existe', () => {
    expect(AUTHENTICATED_HOME_ROUTE).toBe('/');
    expect(routes.some((route) => route.path === AUTHENTICATED_HOME_ROUTE)).toBe(true);
  });
});
