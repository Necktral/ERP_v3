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
      await context.close();
    }
    evidence('accessibility_browser.json', ['axe serious/critical=0', 'teclado/foco visible', '360x800', '768x1024', '1440x900']);
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
