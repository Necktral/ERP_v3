import { NAV } from 'src/app/nav';

const NATIVE_SHELL_ROUTES = new Set([
  '/login',
  '/login/2fa',
  '/bootstrap',
  '/password-change',
  '/select-context',
  '/enrolar',
  '/403',
  '/nomina/sala-de-pago',
]);

function normalizePath(path: string): string {
  const clean = path.split(/[?#]/, 1)[0] || '/';
  return clean.length > 1 ? clean.replace(/\/$/, '') : clean;
}

/** Módulo requerido por una ruta, usando el ítem de navegación más específico. */
export function requiredModuleForPath(path: string): string | null {
  const normalized = normalizePath(path);
  const match = NAV.filter((item) => {
    const base = normalizePath(item.to);
    return normalized === base || normalized.startsWith(`${base}/`);
  }).sort((a, b) => b.to.length - a.to.length)[0];
  return match?.module ?? null;
}

export function hasRequiredModule(path: string, effectiveModules: readonly string[]): boolean {
  const required = requiredModuleForPath(path);
  return required === null || effectiveModules.includes(required);
}

/** La APK es un shell monopropósito: no admite navegación directa al ERP de escritorio. */
export function isAllowedInNativeShell(path: string): boolean {
  return NATIVE_SHELL_ROUTES.has(normalizePath(path));
}
