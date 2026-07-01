import { boot } from 'quasar/wrappers';

/**
 * Soporte de SQLite en WEB (jeep-sqlite) para la app del pagador de nómina.
 *
 * En nativo (Capacitor/Android) no hace nada: el plugin SQLite corre nativo. En el navegador
 * registra el web component `jeep-sqlite` (SQLite compilado a WASM) que el store usa para
 * `initWebStore`. Si algo falla (p. ej. falta el wasm en dev), NO rompe la app: el store cae
 * solo a localStorage. Así el mismo build sirve en tableta (SQLite real) y en navegador.
 */
export default boot(async () => {
  try {
    const { Capacitor } = await import('@capacitor/core');
    if (Capacitor.getPlatform() !== 'web') return;

    const { defineCustomElements } = await import('jeep-sqlite/loader');
    defineCustomElements(window);

    if (!document.querySelector('jeep-sqlite')) {
      document.body.appendChild(document.createElement('jeep-sqlite'));
    }
    await customElements.whenDefined('jeep-sqlite');
  } catch (e) {
    console.warn('[pagador] SQLite web (jeep-sqlite) no disponible; se usará respaldo local:', e);
  }
});
