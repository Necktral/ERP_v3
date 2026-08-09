import type { CreditAccountSummary } from 'src/modules/ventas/api';

export interface HeldCustomer {
  clienteId: number | null;
  clienteNombre?: string;
}

export async function rehydrateHeldCustomer(
  ticket: HeldCustomer,
  loadAccount: (partyId: number) => Promise<CreditAccountSummary | null>,
): Promise<{ id: number | null; name: string; account: CreditAccountSummary | null }> {
  const id = ticket.clienteId;
  return {
    id,
    name: ticket.clienteNombre ?? '',
    account: id == null ? null : await loadAccount(id),
  };
}
