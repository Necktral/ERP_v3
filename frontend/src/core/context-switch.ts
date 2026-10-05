export interface MutableContext {
  activeCompanyId: string | null;
  activeBranchId: string | null;
  setContext(companyId: string | number, branchId?: string | number | null): void;
  clear(): void;
}

/** Cambia el contexto y revierte también el storage si el bootstrap de sesión falla. */
export async function switchContextWithRollback(
  context: MutableContext,
  companyId: string | number,
  branchId: string | number | null,
  refreshSession: () => Promise<unknown>,
): Promise<void> {
  const previous = {
    companyId: context.activeCompanyId,
    branchId: context.activeBranchId,
  };

  context.setContext(companyId, branchId);
  try {
    await refreshSession();
  } catch (error) {
    if (previous.companyId) context.setContext(previous.companyId, previous.branchId);
    else context.clear();
    throw error;
  }
}
