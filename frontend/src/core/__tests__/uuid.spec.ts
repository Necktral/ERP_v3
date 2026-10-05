import { describe, expect, it } from 'vitest';

import { newUuid } from '../uuid';

describe('newUuid', () => {
  it('genera UUID v4 distintos', () => {
    const first = newUuid();
    const second = newUuid();
    const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

    expect(first).toMatch(uuidV4);
    expect(second).toMatch(uuidV4);
    expect(second).not.toBe(first);
  });
});
