import { describe, expect, it, vi } from 'vitest';
import { collectPaginated } from 'src/core/api';

describe('collectPaginated', () => {
  it('incluye la fila posterior al antiguo tope y conserva offsets', async () => {
    const load = vi.fn(({ limit, offset }: { limit: number; offset: number }) => Promise.resolve({
      count: 201,
      limit,
      offset,
      results: Array.from({ length: Math.min(limit, 201 - offset) }, (_, i) => offset + i + 1),
    }));
    const rows = await collectPaginated(load, 200);
    expect(rows).toHaveLength(201);
    expect(rows.at(-1)).toBe(201);
    expect(load).toHaveBeenNthCalledWith(2, { limit: 200, offset: 200 });
  });
});
