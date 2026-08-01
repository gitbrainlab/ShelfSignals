export const SHELF_STORAGE_KEY = "shelfsignals_shelf";
export const JEFFERSON_SHELF_STORAGE_KEY = "shelfsignals_shelf:jefferson";

function normalizeIds(value) {
  const items = Array.isArray(value) ? value : [];
  return [...new Set(items.map(item => typeof item === "string" ? item : item?.id).filter(Boolean))];
}

export function loadShelfIds(storage = globalThis.localStorage, key = SHELF_STORAGE_KEY) {
  try {
    const parsed = JSON.parse(storage?.getItem(key) || "[]");
    return normalizeIds(parsed);
  } catch (_) {
    return [];
  }
}

export function saveShelfIds(ids = [], storage = globalThis.localStorage, key = SHELF_STORAGE_KEY) {
  const normalized = normalizeIds(ids);
  try {
    storage?.setItem(key, JSON.stringify(normalized));
    return { ok: true, ids: normalized };
  } catch (error) {
    return { ok: false, ids: normalized, error };
  }
}

export function toggleShelfId(ids = [], id) {
  const normalized = normalizeIds(ids);
  if (!id) return normalized;
  return normalized.includes(id) ? normalized.filter(candidate => candidate !== id) : [...normalized, id];
}

export function resolveShelfRecords(ids = [], records = []) {
  const byId = new Map(records.map(record => [record.id, record]));
  return normalizeIds(ids).map(id => byId.get(id)).filter(Boolean);
}

export function restoreShelfFromReceipt(receipt = {}, records = [], { collectionId = "sekula" } = {}) {
  const isLegacySekulaReceipt = receipt?.schema === "shelfsignals-receipt@1" && collectionId === "sekula";
  const isMatchingCollectionReceipt = receipt?.schema === "shelfsignals-receipt@2"
    && receipt?.dataset?.id === collectionId;
  if ((!isLegacySekulaReceipt && !isMatchingCollectionReceipt) || !Array.isArray(receipt?.items)) {
    return { valid: false, ids: [], missing: [] };
  }
  const available = new Set(records.map(record => record.id));
  const requested = normalizeIds(receipt.items);
  return {
    valid: true,
    ids: requested.filter(id => available.has(id)),
    missing: requested.filter(id => !available.has(id))
  };
}
