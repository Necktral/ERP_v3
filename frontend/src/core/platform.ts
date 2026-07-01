/**
 * Detección de plataforma — distingue la app nativa (Capacitor) del navegador web.
 *
 * En la app empacada (APK) la auth viaja por token Bearer y el endpoint es una URL
 * absoluta configurable; en web sigue por cookie HttpOnly mismo-origen (`/api`).
 * `Capacitor.isNativePlatform()` es síncrono y en web devuelve `false` (shim web),
 * así que es seguro llamarlo en el arranque.
 */
import { Capacitor } from '@capacitor/core';

export function isNativeApp(): boolean {
  try {
    return Capacitor.isNativePlatform();
  } catch {
    return false;
  }
}

export function platformName(): string {
  try {
    return Capacitor.getPlatform();
  } catch {
    return 'web';
  }
}
