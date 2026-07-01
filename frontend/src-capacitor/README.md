# CO-PA — app móvil (Capacitor), offline-first y EMPACADA

Empaque **Capacitor** de **CO-PA** (Cobrador-Pagador, la **Sala de Pago**). La app es
**monopropósito**: arranca directo en la Sala de Pago y NO expone el resto del ERP (autofactura,
asistencia, etc. — el menú lateral va oculto en nativo).

`appId = io.necktral.erp`, `appName = "CO-PA"`, `webDir = www`.

La UI (`www/`) la genera Quasar (**no la edites a mano**). El proyecto nativo `android/` se regenera con
`npx cap add android` (por eso está en `.gitignore`).

## Arquitectura (offline-first, sin `server.url`)
- **Empacada**: el SPA va DENTRO del APK (`webDir: www`, sin `server.url`). La app abre y opera **sin
  red**: el resumen se cachea en **SQLite** y los pagos se **encolan** (`drainQueue`, idempotente) hasta
  que haya conexión.
- **Auth por token Bearer**: en nativo la sesión NO usa cookie sino `Authorization: Bearer` con
  `X-Auth-Transport: header`. El backend ya lo soporta (login devuelve `{access, refresh}`; el
  autenticador lee el header). Tokens persistidos en el dispositivo; refresh por body con rotación.
- **Servidor configurable (LAN + internet)**: el selector en el login fija el servidor y lo recuerda.
  - Default: **`https://wiscontext-sync.org`** (producción: esta PC vía Cloudflare Tunnel) → datos móviles.
  - Override **LAN**: p. ej. `http://192.168.1.13:8000` (misma WiFi de la PC). `usesCleartextTraffic`
    habilita el http de LAN; el build script lo reaplica (android/ es gitignored).

## Generar el APK
Necesita el stack `docker compose` arriba y, la **primera vez**, descargar el Android SDK a `~/.cache`.

### Rápido (script reproducible)
```bash
bash frontend/src-capacitor/build-apk.sh
# → copia el resultado a ~/CO-PA-debug.apk
```
El script hace: build del SPA (Quasar) → `www` → `cap sync android` → parche del manifest
(`usesCleartextTraffic`) → `gradle assembleDebug` en un contenedor JDK21 con el SDK/Gradle cacheados.

### Manual (equivalente)
```bash
# 1) deps (una vez)
( cd frontend && npm install ) && ( cd frontend/src-capacitor && npm install )
# 2) proyecto Android nativo (una vez; idempotente)
( cd frontend/src-capacitor && npx cap add android )
# 3) build web + sync
docker compose exec -T frontend sh -lc "cd /app/frontend && npx quasar build -m spa"
rm -rf frontend/src-capacitor/www && cp -r frontend/dist/spa frontend/src-capacitor/www
docker compose exec -T frontend sh -lc "cd /app/frontend/src-capacitor && npx cap sync android"
# 4) compilar el APK (Android Studio en Windows, o el contenedor JDK del script)
```
Alternativa visual: abrir `frontend/src-capacitor/android` en **Android Studio** (Gradle sync → Run ▶).

## Instalar en el teléfono
1. Copiar `~/CO-PA-debug.apk` al teléfono (desde Windows: `\\wsl.localhost\<distro>\home\necktral\CO-PA-debug.apk`).
2. Activar "instalar de orígenes desconocidos" y tocar el APK (o `adb install CO-PA-debug.apk`).
3. Abrir CO-PA → si hace falta, tocar **Servidor** en el login para elegir Internet o LAN → ingresar.

## Plugins nativos
- `@capacitor-community/sqlite` — base local de la sala de pago (offline-first).
- `@capacitor/app` — ciclo de vida. `@capacitor-mlkit/barcode-scanning` — escáner (carnet/código).
- `@capacitor/filesystem` + `@capacitor/share` — guardar/compartir el **recibo** en el dispositivo.

## Producción (servidor en ESTA PC bajo `wiscontext-sync.org`)
Ver el runbook de despliegue: [`../../docs/operacion/RUNBOOK_PROD_WISCONTEXT_SYNC.md`](../../docs/operacion/RUNBOOK_PROD_WISCONTEXT_SYNC.md)
(stack `compose.prod.yaml` + Cloudflare Tunnel para TLS automático sin abrir puertos ni DDNS).
