import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('src/boot/axios', () => ({ api: { get, post: vi.fn() } }));

import { listAssets, listAssetsPage, listDrivers, listFuelLogs } from 'src/modules/fleet/api';

describe('paginación de costos de flota', () => {
  beforeEach(() => vi.clearAllMocks());
  it('preserva total y solicita offset posterior', async () => {
    get.mockResolvedValue({ data: { count: 201, limit: 25, offset: 200, results: [{ id: 201 }] } });
    const page = await listFuelLogs(9, { limit: 25, offset: 200 });
    expect(get).toHaveBeenCalledWith('/fleet/assets/9/fuel-logs/', { params: { limit: 25, offset: 200 } });
    expect(page.count).toBe(201);
    expect(page.results[0]?.id).toBe(201);
  });

  it('acota selectores y envía búsqueda remota sin recorrer páginas', async () => {
    get.mockResolvedValue({ data: { count: 500, limit: 25, offset: 0, results: [{ id: 1 }] } });
    await expect(listAssets('TR-01')).resolves.toEqual([{ id: 1 }]);
    expect(get).toHaveBeenLastCalledWith('/fleet/assets/', { params: { limit: 25, offset: 0, search: 'TR-01' } });
    expect(get).toHaveBeenCalledTimes(1);

    get.mockClear();
    await listDrivers('Carlos');
    expect(get).toHaveBeenCalledWith('/fleet/drivers/', { params: { limit: 25, offset: 0, search: 'Carlos' } });
    expect(get).toHaveBeenCalledTimes(1);

    get.mockClear();
    await listAssetsPage({ limit: 25, offset: 200 }, 'camión');
    expect(get).toHaveBeenCalledWith('/fleet/assets/', { params: { limit: 25, offset: 200, search: 'camión' } });
  });
});
