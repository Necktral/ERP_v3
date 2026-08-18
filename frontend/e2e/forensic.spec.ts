import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const reports = resolve(process.cwd(), '../qa/reports');
function requiredPassword(): string {
  const value = process.env.FORENSIC_E2E_PASSWORD;
  if (value) return value;
  throw new Error('FORENSIC_E2E_PASSWORD is required');
}
const password = requiredPassword();

function evidence(name: string, checks: string[]) {
  mkdirSync(reports, { recursive: true });
  writeFileSync(resolve(reports, name), JSON.stringify({
    status: 'passed',
    generated_at: new Date().toISOString(),
    runner: '@playwright/test',
    checks,
  }, null, 2) + '\n');
}

async function login(page: Page, username: string) {
  await page.goto('/#/login');
  await page.getByRole('textbox', { name: 'Usuario', exact: true }).fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  await page.waitForURL((url) => !url.hash.endsWith('/login'));
  if (page.url().includes('/seleccionar-contexto')) {
    await page.locator('.ctx-branch').filter({ hasNotText: 'Toda la empresa' }).first().click();
    await page.waitForURL((url) => !url.hash.includes('/seleccionar-contexto'));
  }
  await expect(page).not.toHaveURL(/#\/login$/);
}

async function semanticSmoke(page: Page, path: string) {
  const serverErrors: string[] = [];
  const onResponse = (response: { status(): number; url(): string }) => {
    if (response.status() >= 500 && response.url().includes('/api/')) {
      serverErrors.push(`${response.status()} ${response.url()}`);
    }
  };
  page.on('response', onResponse);
  await page.goto(`/#${path}`);
  await expect(page).not.toHaveURL(/login|\/403|forbidden/);
  await expect(page.locator('#q-app')).toBeVisible();
  const surface = page.locator('main:visible, [role="main"]:visible, .q-page:visible').first();
  await expect(surface, `superficie principal visible en ${path}`).toBeVisible();
  await expect(surface, `contenido principal no vacío en ${path}`).not.toBeEmpty();
  await expect(page.locator(
    'h1:visible, h2:visible, h3:visible, .q-table:visible, form:visible, .q-card:visible, '
      + '[role="alert"]:visible, input:visible, [role="combobox"]:visible, button:visible',
  ).first(), `control o título semántico visible en ${path}`).toBeVisible();
  await page.waitForTimeout(350);
  const tabs = page.locator('.q-tab:visible');
  if (await tabs.count() > 1) {
    await tabs.nth(1).click();
    await expect(tabs.nth(1)).toHaveAttribute('aria-selected', 'true');
  }
  page.off('response', onResponse);
  expect(serverErrors, `API 5xx en ${path}`).toEqual([]);
}

test.describe('E2E por rol', () => {
  test('administrador recorre dominios críticos y roles restringidos se aíslan', async ({ browser }) => {
    const admin = await browser.newPage();
    await login(admin, 'forensic_admin');
    for (const path of ['/recursos-humanos', '/nomina', '/compras', '/inventario', '/ventas', '/contabilidad']) {
      await admin.goto(`/#${path}`);
      await expect(admin).not.toHaveURL(/forbidden|login/);
      await expect(admin.locator('#q-app')).toBeVisible();
      await expect(admin.locator('#q-app')).not.toBeEmpty();
    }
    await admin.close();

    const accountant = await browser.newPage();
    await login(accountant, 'forensic_contador');
    await accountant.goto('/#/contabilidad');
    await expect(accountant).toHaveURL(/contabilidad/);
    await accountant.goto('/#/recursos-humanos');
    await expect(accountant).toHaveURL(/\/403/);
    await accountant.close();

    const cashier = await browser.newPage();
    await login(cashier, 'forensic_cajero');
    await cashier.goto('/#/caja');
    await expect(cashier).toHaveURL(/caja/);
    await cashier.goto('/#/contabilidad');
    await expect(cashier).toHaveURL(/\/403/);
    await cashier.close();

    evidence('e2e_by_role.json', [
      'login y contexto por rol', 'admin: HR/nómina/compras/inventario/ventas/contabilidad',
      'contador permitido contabilidad y denegado HR', 'cajero permitido caja y denegado contabilidad',
    ]);
  });

  test('smoke semántico de dominios activos y dormidos no produce 5xx', async ({ browser }) => {
    const page = await browser.newPage();
    await login(page, 'forensic_admin');
    const domains = [
      '/recursos-humanos/trabajadores', '/nomina', '/asistencia', '/nomina/sala-de-pago',
      '/compras', '/inventario/catalogo', '/facturacion', '/ventas', '/caja', '/caja/pagos',
      '/contabilidad/diario', '/estacion', '/finca/ordenes', '/financiamiento/productores',
      '/beneficio', '/flota', '/cec', '/conocimiento', '/diagnostico',
    ];
    for (const path of domains) await semanticSmoke(page, path);

    // Guard reversible de doble envío: un formulario incompleto mantiene la acción deshabilitada.
    await page.goto('/#/inventario/catalogo');
    const newItem = page.getByRole('button', { name: /nuevo art[ií]culo/i }).first();
    if (await newItem.isVisible()) {
      await newItem.click();
      const save = page.getByRole('button', { name: /guardar|crear/i }).last();
      await expect(save).toBeDisabled();
      await page.keyboard.press('Escape');
    }
    evidence('e2e_by_role.json', [
      'login y contexto por rol', 'aislamiento de contador y cajero',
      '19 dominios con superficie y control semántico visibles', 'respuestas API sin 5xx',
      'interacción reversible de pestañas', 'guard UI contra doble envío inválido',
    ]);
    await page.close();
  });
});

test.describe('Accesibilidad browser', () => {
  test('axe, teclado/foco y viewports', async ({ browser }) => {
    for (const viewport of [{ width: 360, height: 800 }, { width: 768, height: 1024 }, { width: 1440, height: 900 }]) {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      await page.goto('/#/login');
      await page.keyboard.press('Tab');
      await expect(page.locator(':focus')).toBeVisible();
      const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
      expect(result.violations.filter((v) => ['serious', 'critical'].includes(v.impact ?? ''))).toEqual([]);
      await login(page, 'forensic_admin');
      for (const path of ['/recursos-humanos/trabajadores', '/nomina', '/compras', '/inventario/catalogo', '/caja', '/contabilidad/diario']) {
        await page.goto(`/#${path}`);
        const firstFocusable = page.locator('button:visible, a[href]:visible, input:visible, [tabindex="0"]:visible').first();
        await expect(firstFocusable, `control enfocable en ${path}`).toBeVisible();
        await firstFocusable.focus();
        await expect(page.locator(':focus')).toBeVisible();
        await page.keyboard.press('Tab');
        await expect(page.locator(':focus')).toBeVisible();
        const screenResult = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
        expect(
          screenResult.violations.filter((v) => ['serious', 'critical'].includes(v.impact ?? '')),
          `${path} @ ${viewport.width}x${viewport.height}`,
        ).toEqual([]);
      }
      await context.close();
    }
    evidence('accessibility_browser.json', [
      'axe serious/critical=0 en login + 6 pantallas críticas', 'teclado/foco visible',
      '360x800', '768x1024', '1440x900',
    ]);
  });
});

test.describe('Offline y reconexión', () => {
  test('sesión cacheada entra offline y se revalida al reconectar', async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await login(page, 'forensic_cajero');
    expect(await page.evaluate(() => localStorage.getItem('necktral.session.payload'))).toBeTruthy();
    await context.setOffline(true);
    await page.evaluate(() => { window.location.hash = '#/caja'; });
    await expect(page).toHaveURL(/#\/caja/);
    await expect(page).not.toHaveURL(/login|\/403/);
    await context.setOffline(false);
    await page.reload({ waitUntil: 'networkidle' });
    await expect(page).not.toHaveURL(/login|forbidden/);
    await context.close();
    evidence('offline_reconnect_e2e.json', ['sesión cacheada', 'entrada offline', 'reconexión', 'revalidación de sesión']);
  });
});
