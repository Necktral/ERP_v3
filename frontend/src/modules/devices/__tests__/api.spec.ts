import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('src/boot/axios', () => ({ api: { get, post } }));

import { listDevices, revokeDevice } from 'src/modules/devices/api';

describe('API de dispositivos paginada', () => {
  beforeEach(() => vi.clearAllMocks());

  it('preserva count/next y solicita la página posterior a 200', async () => {
    get.mockResolvedValue({ data: { count: 201, next: null, previous: '/sync/devices/?limit=25&offset=175', results: [{ id: 'device-201' }] } });
    const page = await listDevices(25, 200);
    expect(get).toHaveBeenCalledWith('/sync/devices/', { params: { limit: 25, offset: 200 } });
    expect(page.count).toBe(201);
    expect(page.results[0]?.id).toBe('device-201');
  });

  it('permite revocar un dispositivo obtenido en una página posterior', async () => {
    await revokeDevice('device-201');
    expect(post).toHaveBeenCalledWith('/sync/devices/device-201/revoke/', {});
  });
});
