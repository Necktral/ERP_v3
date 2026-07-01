/**
 * Intercompañía (kernel `intercompany`) — posición de cartera de grupo.
 * Endpoint: GET /intercompany/group-cartera/?company_ids=2,4 (perm audit.read).
 */
import { api } from 'src/boot/axios';

export async function getGroupCartera(companyIds: number[]): Promise<Record<string, unknown>> {
  const { data } = await api.get<Record<string, unknown>>('/intercompany/group-cartera/', {
    params: { company_ids: companyIds.join(',') },
  });
  return data;
}
