import { describe, expect, it } from 'vitest';
import { LatestRequest } from 'src/core/latest-request';

describe('LatestRequest', () => {
  it('impide que A lenta sobrescriba B rápida', async () => {
    const gate = new LatestRequest();
    let visible = '';
    let resolveA!: (value: string) => void;
    const slowA = new Promise<string>((resolve) => { resolveA = resolve; });
    const currentA = gate.begin();
    const requestA = slowA.then((value) => { if (currentA()) visible = value; });
    const currentB = gate.begin();
    await Promise.resolve('B').then((value) => { if (currentB()) visible = value; });
    resolveA('A');
    await requestA;
    expect(visible).toBe('B');
  });
});
