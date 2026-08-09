import { describe, expect, it } from 'vitest';
import { createSessionCache, readValidSessionCache } from 'src/core/storage/session-cache';

describe('offline session cache', () => {
  it('acepta el envelope vigente', () => {
    const raw = JSON.stringify(createSessionCache({ user: 7 }, 1_000, 5_000));
    expect(readValidSessionCache(raw, 5_999)).toEqual({ user: 7 });
  });

  it('rechaza caché vencida, legacy o corrupta', () => {
    const expired = JSON.stringify(createSessionCache({ user: 7 }, 1_000, 5_000));
    expect(readValidSessionCache(expired, 6_000)).toBeNull();
    expect(readValidSessionCache(JSON.stringify({ user: 7 }), 2_000)).toBeNull();
    expect(readValidSessionCache('{', 2_000)).toBeNull();
  });
});
