import { describe, expect, it, vi } from 'vitest';
import { rehydrateHeldCustomer } from 'src/modules/ventas/held-ticket';

describe('ticket POS en espera', () => {
  it('restaura nombre y reconsulta crédito por ID', async () => {
    const account = { account_id: 1, party_id: 7 };
    const load = vi.fn().mockResolvedValue(account);
    const restored = await rehydrateHeldCustomer(
      { clienteId: 7, clienteNombre: 'Café Norte' },
      load,
    );
    expect(restored).toEqual({ id: 7, name: 'Café Norte', account });
    expect(load).toHaveBeenCalledWith(7);
  });

  it('tolera tickets legacy y consumidor final', async () => {
    const load = vi.fn();
    await expect(rehydrateHeldCustomer({ clienteId: null }, load)).resolves.toEqual({
      id: null,
      name: '',
      account: null,
    });
    expect(load).not.toHaveBeenCalled();
  });
});
