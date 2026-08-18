import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('src/boot/axios', () => ({ api: { get, post: vi.fn(), patch: vi.fn(), put: vi.fn() } }));

import { listPlotsPage } from 'src/modules/finca/api';
import { listItemsPage } from 'src/modules/inventory/api';

describe('selectores remotos de finca', () => {
  beforeEach(() => vi.clearAllMocks());

  it('busca lotes en una sola página acotada', async () => {
    get.mockResolvedValue({ data: { count: 400, limit: 25, offset: 0, results: [] } });
    await listPlotsPage({ limit: 25, offset: 0 }, 9, 'café');
    expect(get).toHaveBeenCalledWith('/finca/plots/', {
      params: { limit: 25, offset: 0, finca_id: 9, search: 'café' },
    });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('busca artículos activos sin descargar el catálogo', async () => {
    get.mockResolvedValue({ data: { count: 800, limit: 25, offset: 0, results: [] } });
    await listItemsPage({ search: 'fertilizante', is_active: true }, { limit: 25, offset: 0 });
    expect(get).toHaveBeenCalledWith('/inventory/items/', {
      params: { limit: 25, offset: 0, search: 'fertilizante', is_active: true },
    });
    expect(get).toHaveBeenCalledTimes(1);
  });
});
