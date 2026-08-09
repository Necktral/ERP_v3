import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? vueFiles(path) : entry.name.endsWith('.vue') ? [path] : [];
  });
}

describe('guardas UX estáticas', () => {
  it('todo q-btn redondo con icono tiene nombre accesible', () => {
    const offenders: string[] = [];
    for (const file of vueFiles(join(process.cwd(), 'src/modules'))) {
      const source = readFileSync(file, 'utf8');
      for (const match of source.matchAll(/<q-btn\b[^>]*>/gs)) {
        const tag = match[0];
        if (/\bround\b/.test(tag) && /\bicon=/.test(tag) && !/\b(label|aria-label)=/.test(tag)) {
          offenders.push(`${file}:${source.slice(0, match.index).split('\n').length}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('los diálogos críticos no fuerzan un mínimo mayor al viewport móvil', () => {
    const targets = [
      join(process.cwd(), 'src/modules/inventory/pages/ListasPreciosPage.vue'),
      join(process.cwd(), 'src/modules/nomina/pages/RegimenInssPage.vue'),
    ];
    for (const file of targets) expect(readFileSync(file, 'utf8')).not.toMatch(/style="min-width:\s*(?:3[6-9]\d|[4-9]\d\d)px"/);
  });
});
