import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? vueFiles(path) : entry.name.endsWith('.vue') ? [path] : [];
  });
}

describe('guardas UX estáticas', () => {
  it('permite zoom móvil y nombra la barra global de carga', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8');
    const boot = readFileSync(resolve(process.cwd(), 'src/boot/accessibility.ts'), 'utf8');
    expect(html).not.toContain('user-scalable=no');
    expect(html).not.toContain('maximum-scale=1');
    expect(boot).toContain("setAttribute('aria-label', 'Cargando página')");
  });
  it('expone navegación con rol correcto y tablas desplazables enfocables', () => {
    const layout = readFileSync(resolve(process.cwd(), 'src/layouts/AppLayout.vue'), 'utf8');
    const boot = readFileSync(resolve(process.cwd(), 'src/boot/accessibility.ts'), 'utf8');
    expect(layout).toContain('role="navigation" aria-label="Navegación principal"');
    expect(boot).toContain(".q-table__middle.scroll");
    expect(boot).toContain("setAttribute('tabindex', '0')");
  });
  it('mantiene tooltips opacos con contraste alto', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/css/app.scss'), 'utf8');
    expect(css).toMatch(/\.q-tooltip\s*\{[^}]*background:\s*#1b1b1b\s*!important/si);
    expect(css).toMatch(/\.q-tooltip\s*\{[^}]*color:\s*#fff\s*!important/si);
    expect(css).toMatch(/\.q-tooltip\s*\{[^}]*opacity:\s*1\s*!important/si);
  });
  it('nombra la selección masiva y por fila del catálogo de inventario', () => {
    const catalog = readFileSync(
      resolve(process.cwd(), 'src/modules/inventory/pages/CatalogoInventarioPage.vue'),
      'utf8',
    );
    expect(catalog).toContain('aria-label="Seleccionar todos los artículos"');
    expect(catalog).toContain(':aria-label="`Seleccionar artículo ${scope.row.sku || scope.row.name || scope.row.id}`"');
  });
  it('usa texto verde de alto contraste para el estado en línea', () => {
    const connectivity = readFileSync(
      resolve(process.cwd(), 'src/components/ConnectivityDot.vue'),
      'utf8',
    );
    expect(connectivity).toMatch(/\.conn--on \.conn__label\s*\{[^}]*color:\s*#137333/si);
    expect(connectivity).not.toMatch(/\.conn--on \.conn__label\s*\{[^}]*var\(--q-positive\)/si);
  });
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
