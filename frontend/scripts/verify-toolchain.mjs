import { access, realpath, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { resolve } from 'node:path';

const tools = ['eslint', 'vue-tsc', 'vitest', 'quasar'];
const failures = [];

for (const tool of tools) {
  const launcher = resolve('node_modules', '.bin', tool);
  try {
    await access(launcher, constants.X_OK);
    const target = await realpath(launcher);
    const info = await stat(target);
    if (!info.isFile() || info.size === 0) {
      failures.push(`${tool}: destino inválido o vacío (${target})`);
    }
  } catch (error) {
    failures.push(`${tool}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

if (failures.length > 0) {
  console.error('[toolchain] instalación inválida; ejecutá npm ci desde frontend/');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(`[toolchain] OK: ${tools.join(', ')}`);
