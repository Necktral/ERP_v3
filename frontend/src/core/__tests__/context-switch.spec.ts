import { describe, expect, it, vi } from 'vitest';
import { switchContextWithRollback, type MutableContext } from 'src/core/context-switch';

function context(companyId: string | null, branchId: string | null): MutableContext {
  return {
    activeCompanyId: companyId,
    activeBranchId: branchId,
    setContext(company, branch) {
      this.activeCompanyId = String(company);
      this.activeBranchId = branch == null ? null : String(branch);
    },
    clear() {
      this.activeCompanyId = null;
      this.activeBranchId = null;
    },
  };
}

describe('switchContextWithRollback', () => {
  it('conserva el contexto nuevo cuando el bootstrap termina', async () => {
    const ctx = context('1', '10');
    const refresh = vi.fn().mockResolvedValue(undefined);
    await switchContextWithRollback(ctx, '2', '20', refresh);
    expect([ctx.activeCompanyId, ctx.activeBranchId]).toEqual(['2', '20']);
  });

  it('restaura empresa y sucursal si el bootstrap falla', async () => {
    const ctx = context('1', '10');
    const refresh = vi.fn().mockRejectedValue(new Error('sin red'));
    await expect(switchContextWithRollback(ctx, '2', '20', refresh)).rejects.toThrow('sin red');
    expect([ctx.activeCompanyId, ctx.activeBranchId]).toEqual(['1', '10']);
  });

  it('vuelve a contexto vacío si no existía uno anterior', async () => {
    const ctx = context(null, null);
    await expect(
      switchContextWithRollback(ctx, '2', '20', () => Promise.reject(new Error('falló'))),
    ).rejects.toThrow('falló');
    expect([ctx.activeCompanyId, ctx.activeBranchId]).toEqual([null, null]);
  });
});
