#!/usr/bin/env bash
# Construye el APK de CO-PA (offline-first, EMPACADO — sin server.url).
#
# Reproduce todo el flujo de punta a punta usando los contenedores del stack:
#   1) build del SPA (Quasar)  → 2) copiar a www  → 3) cap sync android
#   4) parche del manifest (usesCleartextTraffic; android/ es gitignored → hay que reaplicarlo)
#   5) gradle assembleDebug en un contenedor JDK21 + SDK cacheado en ~/.cache
#
# Requisitos: stack `docker compose` arriba (contenedor `frontend`) + las cachés de Android en
# ~/.cache/android-sdk y ~/.cache/android-gradle (se crean en el primer build; ver README).
# Uso:  bash frontend/src-capacitor/build-apk.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # raíz del repo
FE="$ROOT/frontend"
CAP="$FE/src-capacitor"
COMPOSE="$ROOT/compose.yaml"

echo ">> 1/5 build del SPA (Quasar) en el contenedor frontend"
docker compose -f "$COMPOSE" exec -T frontend sh -lc "cd /app/frontend && npx quasar build -m spa"

echo ">> 2/5 copiar el build a src-capacitor/www"
rm -rf "$CAP/www"
cp -r "$FE/dist/spa" "$CAP/www"
test -f "$CAP/www/index.html" || { echo "ERROR: www/index.html no se generó"; exit 1; }

echo ">> 3/5 cap sync android (copia www + config al proyecto nativo)"
docker compose -f "$COMPOSE" exec -T frontend sh -lc "cd /app/frontend/src-capacitor && npx cap sync android"

echo ">> 4/5 parche del manifest: usesCleartextTraffic (necesario para el fallback de servidor en LAN por http)"
MAN="$CAP/android/app/src/main/AndroidManifest.xml"
if ! grep -q 'usesCleartextTraffic' "$MAN"; then
  sed -i 's#android:supportsRtl="true"#android:supportsRtl="true"\n        android:usesCleartextTraffic="true"#' "$MAN"
  echo "   parche aplicado."
else
  echo "   ya estaba presente."
fi

echo ">> 5/5 gradle assembleDebug (JDK21 + SDK/Gradle cacheados)"
docker run --rm -i \
  -v "$CAP":/project \
  -v "$HOME/.cache/android-sdk":/opt/android-sdk \
  -v "$HOME/.cache/android-gradle":/root/.gradle \
  --entrypoint bash erp_crm-backend:latest -s <<'CONTAINER'
set -e
export DEBIAN_FRONTEND=noninteractive
command -v javac >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq --no-install-recommends openjdk-21-jdk-headless ca-certificates >/dev/null; }
export JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")"
export ANDROID_HOME=/opt/android-sdk ANDROID_SDK_ROOT=/opt/android-sdk GRADLE_USER_HOME=/root/.gradle
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
cd /project/android && chmod +x gradlew
./gradlew assembleDebug --no-daemon -Dorg.gradle.jvmargs=-Xmx3g
CONTAINER

APK="$CAP/android/app/build/outputs/apk/debug/app-debug.apk"
cp "$APK" "$HOME/CO-PA-debug.apk"
echo ">> APK listo: $HOME/CO-PA-debug.apk"
ls -la "$HOME/CO-PA-debug.apk"
