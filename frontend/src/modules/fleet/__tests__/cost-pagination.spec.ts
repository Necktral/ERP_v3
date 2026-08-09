import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('src/boot/axios', () => ({ api: { get, post: vi.fn() } }));

import { listFuelLogs } from 'src/modules/fleet/api';

describe('paginación de costos de flota', () => {
  beforeEach(() => vi.clearAllMocks());
  it('preserva total y solicita offset posterior', async () => {
    get.mockResolvedValue({ data: { count: 201, limit: 25, offset: 200, results: [{ id: 201 }] } });
    const page = await listFuelLogs(9, { limit: 25, offset: 200 });
    expect(get).toHaveBeenCalledWith('/fleet/assets/9/fuel-logs/', { params: { limit: 25, offset: 200 } });
    expect(page.count).toBe(201);
    expect(page.results[0]?.id).toBe(201);
  });
});
