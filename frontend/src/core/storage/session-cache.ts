export const DEFAULT_OFFLINE_SESSION_TTL_MS = 24 * 60 * 60 * 1000;

interface SessionCacheEnvelope<T> {
  version: 1;
  cached_at: string;
  expires_at: string;
  data: T;
}

export function createSessionCache<T>(
  data: T,
  nowMs = Date.now(),
  ttlMs = DEFAULT_OFFLINE_SESSION_TTL_MS,
): SessionCacheEnvelope<T> {
  return {
    version: 1,
    cached_at: new Date(nowMs).toISOString(),
    expires_at: new Date(nowMs + ttlMs).toISOString(),
    data,
  };
}

export function readValidSessionCache<T>(raw: string, nowMs = Date.now()): T | null {
  try {
    const parsed = JSON.parse(raw) as Partial<SessionCacheEnvelope<T>>;
    if (parsed.version !== 1 || !parsed.data || typeof parsed.expires_at !== 'string') return null;
    const expiresAt = Date.parse(parsed.expires_at);
    return Number.isFinite(expiresAt) && expiresAt > nowMs ? parsed.data : null;
  } catch {
    return null;
  }
}
