/**
 * Persistencia local de la sala de pago — offline-first.
 *
 * Implementa `PayrollStore` con tres respaldos, en orden de preferencia:
 *   1. SQLite (`@capacitor-community/sqlite`): nativo en la tableta, WASM (jeep-sqlite) en web.
 *   2. localStorage: respaldo en navegador si el WASM de SQLite no está disponible (dev).
 *   3. Memoria: último recurso / pruebas (sin `window`).
 *
 * El mismo código corre en dispositivo (SQLite real) y en el navegador. La app SIEMPRE
 * obtiene un store usable: si SQLite falla al iniciar, degrada sin romper la pantalla.
 */
import type { SQLiteConnection, SQLiteDBConnection } from '@capacitor-community/sqlite';

import type { PaySummaryResponse } from '../api';
import type { PayrollPaymentCommand, PayrollStore } from './queue';

const DB_NAME = 'pagador_nomina';

interface CommandRow {
  data: string;
}

// --- SQLite (nativo + WASM web) ----------------------------------------------

class SqliteStore implements PayrollStore {
  // Tipos del plugin (import type, sin coste en runtime); los valores se cargan dinámico en init().
  private db: SQLiteDBConnection | null = null;
  private sqlite: SQLiteConnection | null = null;
  private web = false;

  backend(): 'sqlite' | 'memory' {
    return 'sqlite';
  }

  async init(): Promise<void> {
    const { CapacitorSQLite, SQLiteConnection } = await import('@capacitor-community/sqlite');
    const { Capacitor } = await import('@capacitor/core');
    this.web = Capacitor.getPlatform() === 'web';
    this.sqlite = new SQLiteConnection(CapacitorSQLite);
    if (this.web) {
      // En web requiere el web component jeep-sqlite ya registrado (boot/sqlite.ts).
      await this.sqlite.initWebStore();
    }

    const consistency = await this.sqlite.checkConnectionsConsistency().catch(() => ({ result: false }));
    const isConn = (await this.sqlite.isConnection(DB_NAME, false)).result === true;
    this.db =
      consistency.result && isConn
        ? await this.sqlite.retrieveConnection(DB_NAME, false)
        : await this.sqlite.createConnection(DB_NAME, false, 'no-encryption', 1, false);

    await this.db.open();
    await this.db.execute(`
      CREATE TABLE IF NOT EXISTS pay_summary (
        period_key TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS payment_queue (
        id TEXT PRIMARY KEY,
        entry_id INTEGER NOT NULL,
        data TEXT NOT NULL
      );
    `);
    await this.persist();
  }

  private async persist(): Promise<void> {
    if (this.web && this.sqlite) await this.sqlite.saveToStore(DB_NAME);
  }

  async cacheSummary(key: string, payload: PaySummaryResponse): Promise<void> {
    if (!this.db) throw new Error('SQLite no inicializado');
    await this.db.run(
      'INSERT OR REPLACE INTO pay_summary (period_key, payload, updated_at) VALUES (?, ?, ?)',
      [key, JSON.stringify(payload), new Date().toISOString()],
    );
    await this.persist();
  }

  async readSummary(key: string): Promise<PaySummaryResponse | null> {
    if (!this.db) throw new Error('SQLite no inicializado');
    const res = await this.db.query('SELECT payload FROM pay_summary WHERE period_key = ?', [key]);
    const rows = (res.values ?? []) as { payload: string }[];
    const row = rows[0];
    return row ? (JSON.parse(row.payload) as PaySummaryResponse) : null;
  }

  async enqueue(cmd: PayrollPaymentCommand): Promise<void> {
    if (!this.db) throw new Error('SQLite no inicializado');
    await this.db.run('INSERT OR REPLACE INTO payment_queue (id, entry_id, data) VALUES (?, ?, ?)', [
      cmd.id,
      cmd.entry_id,
      JSON.stringify(cmd),
    ]);
    await this.persist();
  }

  async updateCommand(id: string, patch: Partial<PayrollPaymentCommand>): Promise<void> {
    if (!this.db) throw new Error('SQLite no inicializado');
    const res = await this.db.query('SELECT data FROM payment_queue WHERE id = ?', [id]);
    const rows = (res.values ?? []) as CommandRow[];
    const row = rows[0];
    if (!row) return;
    const merged = { ...(JSON.parse(row.data) as PayrollPaymentCommand), ...patch };
    await this.db.run('UPDATE payment_queue SET data = ? WHERE id = ?', [JSON.stringify(merged), id]);
    await this.persist();
  }

  async listCommands(): Promise<PayrollPaymentCommand[]> {
    if (!this.db) throw new Error('SQLite no inicializado');
    const res = await this.db.query('SELECT data FROM payment_queue');
    const rows = (res.values ?? []) as CommandRow[];
    return rows.map((r) => JSON.parse(r.data) as PayrollPaymentCommand);
  }
}

// --- Respaldo en navegador (localStorage) ------------------------------------

class LocalStore implements PayrollStore {
  private readonly summaryKey = 'necktral.pagador.summary';
  private readonly queueKey = 'necktral.pagador.queue';

  backend(): 'sqlite' | 'memory' {
    return 'memory';
  }

  init(): Promise<void> {
    return Promise.resolve();
  }

  private readMap<T>(key: string): Record<string, T> {
    const raw = localStorage.getItem(key);
    if (!raw) return {};
    try {
      return JSON.parse(raw) as Record<string, T>;
    } catch {
      return {};
    }
  }

  cacheSummary(key: string, payload: PaySummaryResponse): Promise<void> {
    const map = this.readMap<PaySummaryResponse>(this.summaryKey);
    map[key] = payload;
    localStorage.setItem(this.summaryKey, JSON.stringify(map));
    return Promise.resolve();
  }

  readSummary(key: string): Promise<PaySummaryResponse | null> {
    return Promise.resolve(this.readMap<PaySummaryResponse>(this.summaryKey)[key] ?? null);
  }

  enqueue(cmd: PayrollPaymentCommand): Promise<void> {
    const map = this.readMap<PayrollPaymentCommand>(this.queueKey);
    map[cmd.id] = cmd;
    localStorage.setItem(this.queueKey, JSON.stringify(map));
    return Promise.resolve();
  }

  updateCommand(id: string, patch: Partial<PayrollPaymentCommand>): Promise<void> {
    const map = this.readMap<PayrollPaymentCommand>(this.queueKey);
    const current = map[id];
    if (current) {
      map[id] = { ...current, ...patch };
      localStorage.setItem(this.queueKey, JSON.stringify(map));
    }
    return Promise.resolve();
  }

  listCommands(): Promise<PayrollPaymentCommand[]> {
    return Promise.resolve(Object.values(this.readMap<PayrollPaymentCommand>(this.queueKey)));
  }
}

// --- Memoria pura (pruebas / último recurso) ---------------------------------

export class MemoryStore implements PayrollStore {
  private summaries = new Map<string, PaySummaryResponse>();
  private commands = new Map<string, PayrollPaymentCommand>();

  backend(): 'sqlite' | 'memory' {
    return 'memory';
  }

  init(): Promise<void> {
    return Promise.resolve();
  }

  cacheSummary(key: string, payload: PaySummaryResponse): Promise<void> {
    this.summaries.set(key, payload);
    return Promise.resolve();
  }

  readSummary(key: string): Promise<PaySummaryResponse | null> {
    return Promise.resolve(this.summaries.get(key) ?? null);
  }

  enqueue(cmd: PayrollPaymentCommand): Promise<void> {
    this.commands.set(cmd.id, cmd);
    return Promise.resolve();
  }

  updateCommand(id: string, patch: Partial<PayrollPaymentCommand>): Promise<void> {
    const current = this.commands.get(id);
    if (current) this.commands.set(id, { ...current, ...patch });
    return Promise.resolve();
  }

  listCommands(): Promise<PayrollPaymentCommand[]> {
    return Promise.resolve([...this.commands.values()]);
  }
}

/** Crea un store de memoria pura (para pruebas). */
export function createMemoryStore(): PayrollStore {
  return new MemoryStore();
}

let singleton: PayrollStore | null = null;
let lastStoreError = '';

/** Motivo por el que SQLite cayó a respaldo (vacío si SQLite arrancó OK). Para mostrarlo en la UI. */
export function getStoreError(): string {
  return lastStoreError;
}

/** Carrera contra un timeout: si la promesa no resuelve a tiempo, RECHAZA (no se cuelga). */
function withTimeout<T>(p: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`timeout ${label} (${ms}ms)`)), ms);
    p.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (e) => {
        clearTimeout(timer);
        reject(e instanceof Error ? e : new Error(String(e)));
      },
    );
  });
}

/**
 * Obtiene el store de la app: SQLite si arranca, si no localStorage (navegador) o memoria.
 * Cacheado: una sola conexión por sesión.
 *
 * En WEB el SQLite corre sobre `jeep-sqlite` (WASM). Si ese WASM falla al cargar puede COLGAR
 * `init()` sin rechazar; por eso lo corremos con timeout → así caemos al respaldo localStorage
 * en vez de dejar la app esperando para siempre (lo que vaciaba la Sala de pago en web).
 */
export async function getPayrollStore(): Promise<PayrollStore> {
  if (singleton) return singleton;

  const sqlite = new SqliteStore();
  try {
    // 8s: el plugin nativo puede tardar en el arranque frío de un equipo lento; si igual falla,
    // el fallback localStorage también persiste ante corte de luz.
    await withTimeout(sqlite.init(), 8000, 'SQLite init');
    lastStoreError = '';
    singleton = sqlite;
    return singleton;
  } catch (e) {
    lastStoreError = e instanceof Error ? e.message : String(e);
    console.warn('[pagador] SQLite no disponible, se usa respaldo local:', e);
  }

  const fallback: PayrollStore = typeof window !== 'undefined' && 'localStorage' in window ? new LocalStore() : new MemoryStore();
  await fallback.init();
  singleton = fallback;
  return singleton;
}
