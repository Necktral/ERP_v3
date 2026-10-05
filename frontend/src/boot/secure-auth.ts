import { boot } from 'quasar/wrappers';
import { initTokenStorage } from 'src/core/storage/auth';

/** Carga Keystore/Keychain antes de instalar Axios y antes de la primera navegación. */
export default boot(async () => {
  try {
    await initTokenStorage();
  } catch (error) {
    console.error('[auth] No se pudo abrir el almacenamiento seguro nativo.', error);
    throw error;
  }
});
