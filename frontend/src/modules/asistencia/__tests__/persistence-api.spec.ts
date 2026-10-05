import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('src/boot/axios', () => ({ api: { get, post } }));

import {
  getFieldRollcall,
  listFieldApprovalRequests,
  listFieldCrews,
} from 'src/modules/asistencia/api';

describe('asistencia de campo persistida', () => {
  beforeEach(() => vi.clearAllMocks());

  it('carga el pase y las cuadrillas desde la jornada', async () => {
    get
      .mockResolvedValueOnce({ data: { id: 7, work_day_id: 19, lines: [] } })
      .mockResolvedValueOnce({ data: { results: [{ id: 3, work_day_id: 19 }] } });

    await expect(getFieldRollcall(19)).resolves.toMatchObject({ id: 7 });
    await expect(listFieldCrews(19)).resolves.toEqual([{ id: 3, work_day_id: 19 }]);
    expect(get).toHaveBeenNthCalledWith(1, '/nomina/field/work-days/19/rollcall/');
    expect(get).toHaveBeenNthCalledWith(2, '/nomina/field/work-days/19/crews/');
  });

  it('consulta solicitudes SoD persistidas por jornada o bandeja tenant', async () => {
    get.mockResolvedValue({ data: { results: [] } });

    await listFieldApprovalRequests({ workDayId: 19 });
    expect(get).toHaveBeenLastCalledWith(
      '/nomina/field/work-days/19/approve-request/',
      { params: undefined },
    );

    await listFieldApprovalRequests({ status: 'PENDING' });
    expect(get).toHaveBeenLastCalledWith('/nomina/field/approval-requests/', {
      params: { status: 'PENDING' },
    });
  });
});
