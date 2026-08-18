import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('src/boot/axios', () => ({ api: { get, post: vi.fn() } }));

import { listFixationsPage, listLoansPage, listProducersPage, listReceptionsPage } from 'src/modules/financiamiento/api';

describe('paginación remota de financiamiento', () => {
  beforeEach(() => vi.clearAllMocks());

  it('consulta productores después de 500 filas sin descargar el catálogo', async () => {
    get.mockResolvedValue({ data: { count: 526, limit: 25, offset: 500, results: [{ id: 501 }] } });

    const page = await listProducersPage({ limit: 25, offset: 500 }, 'AC-UNICO');

    expect(get).toHaveBeenCalledWith('/financiamiento/producers/', {
      params: { limit: 25, offset: 500, search: 'AC-UNICO' },
    });
    expect(page.count).toBe(526);
    expect(page.results[0]?.id).toBe(501);
  });

  it.each([
    [listReceptionsPage, '/financiamiento/receptions/'],
    [listFixationsPage, '/financiamiento/fixations/'],
  ] as const)('preserva el envelope paginado de %s', async (loader, endpoint) => {
    get.mockResolvedValue({ data: { count: 225, limit: 25, offset: 200, results: [] } });

    const page = await loader({ limit: 25, offset: 200 });

    expect(get).toHaveBeenCalledWith(endpoint, { params: { limit: 25, offset: 200 } });
    expect(page.count).toBe(225);
  });

  it('busca préstamos activos remotamente con una sola página acotada', async () => {
    get.mockResolvedValue({ data: { count: 600, limit: 25, offset: 0, results: [] } });
    await listLoansPage({ limit: 25, offset: 0 }, 'ACTIVE', 'PR-2026');
    expect(get).toHaveBeenCalledWith('/financiamiento/loans/', {
      params: { limit: 25, offset: 0, status: 'ACTIVE', search: 'PR-2026' },
    });
    expect(get).toHaveBeenCalledTimes(1);
  });
});
