import { beforeEach, describe, expect, it } from 'vitest';

import { createMemoryStore } from 'src/modules/pagador/offline/store';
import {
  buildPaymentCommand,
  drainQueue,
  enqueuePayment,
  periodKey,
  queueStats,
  type PayrollPaymentCommand,
  type PayrollStore,
} from 'src/modules/pagador/offline/queue';

function cmd(entryId: number, amount = '100.00'): PayrollPaymentCommand {
  return buildPaymentCommand({
    period_id: 5,
    sheet_id: 2,
    entry_id: entryId,
    company_id: 10,
    branch_id: 20,
    employee_key: `emp:${entryId}`,
    full_name: `Trabajador ${entryId}`,
    payment_method: 'CASH',
    amount,
  });
}

describe('cola offline del pagador', () => {
  let store: PayrollStore;

  beforeEach(async () => {
    store = createMemoryStore();
    await store.init();
  });

  it('periodKey es estable y distingue sucursal', () => {
    expect(periodKey(10, 20, 5)).toBe('10:20:5');
    expect(periodKey(10, null, 5)).toBe('10:all:5');
  });

  it('dedupe por línea de planilla (no paga dos veces al mismo trabajador)', async () => {
    const first = await enqueuePayment(store, cmd(101));
    const second = await enqueuePayment(store, cmd(101));
    expect(first.duplicate).toBe(false);
    expect(second.duplicate).toBe(true);
    expect(second.command.id).toBe(first.command.id);
    expect(await store.listCommands()).toHaveLength(1);
  });

  it('drena y marca DONE cuando el envío tiene éxito', async () => {
    await enqueuePayment(store, cmd(102));
    const sent: string[] = [];
    const res = await drainQueue(store, async (c) => {
      sent.push(c.id);
      return Promise.resolve();
    });
    expect(res.succeeded).toBe(1);
    expect(sent).toHaveLength(1);
    const cmds = await store.listCommands();
    expect(cmds[0]?.status).toBe('DONE');
  });

  it('un error 422 (sobrepago) NO se reintenta → FAILED', async () => {
    await enqueuePayment(store, cmd(103));
    const err = Object.assign(new Error('excede el neto restante'), {
      response: { status: 422, data: { detail: 'excede el neto restante' } },
    });
    const res = await drainQueue(store, () => Promise.reject(err));
    expect(res.failed).toBe(1);
    expect(res.still_pending).toBe(0);
    const cmds = await store.listCommands();
    expect(cmds[0]?.status).toBe('FAILED');
    expect(cmds[0]?.last_error).toContain('excede');
  });

  it('una caída de red (sin respuesta) se reintenta → PENDING con backoff', async () => {
    await enqueuePayment(store, cmd(104));
    const res = await drainQueue(store, () => Promise.reject(new Error('Network Error')));
    expect(res.still_pending).toBe(1);
    const cmds = await store.listCommands();
    expect(cmds[0]?.status).toBe('PENDING');
    expect(cmds[0]?.attempts).toBe(1);
    expect(cmds[0]?.next_retry_at).not.toBeNull();
  });

  it('queueStats cuenta por estado', async () => {
    await enqueuePayment(store, cmd(105));
    await enqueuePayment(store, cmd(106));
    await drainQueue(store, () => Promise.resolve()); // ambos DONE
    const stats = queueStats(await store.listCommands());
    expect(stats.total).toBe(2);
    expect(stats.done).toBe(2);
    expect(stats.pending).toBe(0);
  });
});
