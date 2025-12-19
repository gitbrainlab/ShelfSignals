/**
 * receipt.js - Digital Receipt System for ShelfSignals
 * 
 * Implements a verifiable, portable data structure for exporting/importing
 * shelf and view configurations without server storage.
 * 
 * Features:
 * - RFC 8785 (JCS) canonical JSON serialization
 * - SHA-256 hashing via WebCrypto API
 * - Human-readable receipt IDs (SS-XXXX-XXXX-XXXX)
 * - QR code generation for sharing
 * - URL fragment encoding for shareable links
 */

/**
 * Canonical JSON stringification (RFC 8785 - JCS)
 * Recursively sorts object keys and removes whitespace
 */
function canonicalStringify(obj) {
  if (obj === null || obj === undefined) {
    return 'null';
  }
  
  if (typeof obj === 'boolean') {
    return obj ? 'true' : 'false';
  }
  
  if (typeof obj === 'number') {
    // Handle special number cases per RFC 8785
    if (!isFinite(obj)) {
      return 'null';
    }
    return String(obj);
  }
  
  if (typeof obj === 'string') {
    return JSON.stringify(obj);
  }
  
  if (Array.isArray(obj)) {
    const items = obj.map(item => canonicalStringify(item));
    return '[' + items.join(',') + ']';
  }
  
  if (typeof obj === 'object') {
    const keys = Object.keys(obj).sort();
    const pairs = keys.map(key => {
      const value = canonicalStringify(obj[key]);
      return JSON.stringify(key) + ':' + value;
    });
    return '{' + pairs.join(',') + '}';
  }
  
  return 'null';
}

/**
 * Compute SHA-256 hash of canonical JSON
 */
async function hashCanonicalJSON(obj) {
  const canonical = canonicalStringify(obj);
  const encoder = new TextEncoder();
  const data = encoder.encode(canonical);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Generate human-readable receipt ID (SS-XXXX-XXXX-XXXX)
 */
function generateReceiptID() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  const segments = 3;
  const segmentLength = 4;
  
  const parts = [];
  for (let i = 0; i < segments; i++) {
    let segment = '';
    for (let j = 0; j < segmentLength; j++) {
      segment += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    parts.push(segment);
  }
  
  return 'SS-' + parts.join('-');
}

/**
 * Compute index hash for dataset verification
 */
async function computeDatasetHash(datasetUrl) {
  try {
    const response = await fetch(datasetUrl);
    const text = await response.text();
    const encoder = new TextEncoder();
    const data = encoder.encode(text);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  } catch (e) {
    console.warn('Failed to compute dataset hash:', e);
    return 'unavailable';
  }
}

/**
 * Create a digital receipt from shelf items or current view
 */
export async function createReceipt(options = {}) {
  const {
    mode = 'shelf', // 'shelf' | 'view'
    items = [],
    filters = {},
    datasetName = 'Allan Sekula Library',
    datasetUrl = null,
    appVersion = 'v2.x'
  } = options;
  
  // Compute dataset hash if URL provided
  let indexHash = 'not-computed';
  if (datasetUrl) {
    indexHash = await computeDatasetHash(datasetUrl);
  }
  
  // Build receipt payload (without hash yet)
  const payload = {
    schema: 'shelfsignals-receipt@1',
    createdAt: new Date().toISOString(),
    app: {
      name: 'ShelfSignals',
      channel: 'preview',
      version: appVersion
    },
    dataset: {
      name: datasetName,
      indexHash: indexHash
    },
    mode: mode,
    items: items.map(item => item.id || item),
    filters: filters
  };
  
  // Compute hash of payload
  const hashValue = await hashCanonicalJSON(payload);
  
  // Add hash and receiptId to final receipt
  const receipt = {
    ...payload,
    hash: {
      alg: 'sha256',
      value: hashValue
    },
    receiptId: generateReceiptID()
  };
  
  return receipt;
}

/**
 * Verify a receipt's hash
 */
export async function verifyReceipt(receipt) {
  if (!receipt || !receipt.hash || !receipt.hash.value) {
    return { valid: false, reason: 'Missing hash' };
  }
  
  // Extract hash and create payload without it
  const { hash, receiptId, ...payload } = receipt;
  
  // Recompute hash
  const computedHash = await hashCanonicalJSON(payload);
  
  // Compare
  const valid = computedHash === hash.value;
  
  return {
    valid,
    reason: valid ? 'Hash verified' : 'Hash mismatch',
    computedHash,
    providedHash: hash.value
  };
}

/**
 * Export receipt as JSON file download
 */
export function downloadReceipt(receipt, filename = null) {
  const name = filename || `shelfsignals-${receipt.mode}-${receipt.receiptId}.json`;
  const json = JSON.stringify(receipt, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Copy receipt as formatted text
 */
export function copyReceiptText(receipt) {
  const text = `ShelfSignals Digital Receipt
Receipt ID: ${receipt.receiptId}
Mode: ${receipt.mode}
Created: ${new Date(receipt.createdAt).toLocaleString()}
Items: ${receipt.items.length}
Dataset: ${receipt.dataset.name}
Hash: ${receipt.hash.value.substring(0, 16)}...

Verify at: ${window.location.origin}/preview/exhibit/#r=${encodeReceiptToFragment(receipt)}`;
  
  // Attempt to copy to clipboard (async operation)
  try {
    await navigator.clipboard.writeText(text);
    return { success: true, text };
  } catch (err) {
    console.error('Failed to copy:', err);
    return { success: false, text };
  }
}

/**
 * Encode receipt to URL fragment (base64url)
 * For large receipts, consider using compression library like pako
 */
export function encodeReceiptToFragment(receipt) {
  const json = JSON.stringify(receipt);
  const encoder = new TextEncoder();
  const data = encoder.encode(json);
  
  // Convert to base64url safely for large arrays
  const bytes = new Uint8Array(data);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  const base64 = btoa(binary);
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

/**
 * Decode receipt from URL fragment
 */
export function decodeReceiptFromFragment(fragment) {
  try {
    // Reverse base64url encoding
    const base64 = fragment.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - base64.length % 4) % 4);
    const data = atob(padded);
    const bytes = new Uint8Array(data.length);
    for (let i = 0; i < data.length; i++) {
      bytes[i] = data.charCodeAt(i);
    }
    const decoder = new TextDecoder();
    const json = decoder.decode(bytes);
    return JSON.parse(json);
  } catch (e) {
    console.error('Failed to decode receipt:', e);
    return null;
  }
}

/**
 * Generate QR code data URL for receipt
 * Returns a simple SVG QR code for client-side generation
 * For production, consider using a proper QR library like qrcode.js
 */
export async function generateQRCode(receipt) {
  const url = `${window.location.origin}${window.location.pathname}#r=${encodeReceiptToFragment(receipt)}`;
  
  // For now, generate a simple placeholder SVG
  // In production, use a proper client-side QR library (e.g., qrcode.js, qrcodegen)
  const placeholderSVG = `data:image/svg+xml,${encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">
      <rect width="300" height="300" fill="white"/>
      <text x="150" y="140" font-family="Arial" font-size="16" text-anchor="middle" fill="#333">
        QR Code Placeholder
      </text>
      <text x="150" y="160" font-family="Arial" font-size="12" text-anchor="middle" fill="#666">
        Add qrcode.js library for
      </text>
      <text x="150" y="175" font-family="Arial" font-size="12" text-anchor="middle" fill="#666">
        full QR code generation
      </text>
    </svg>
  `)}`;
  
  return {
    dataUrl: placeholderSVG,
    url: url
  };
}

/**
 * Parse receipt from URL hash on page load
 */
export function getReceiptFromURL() {
  const hash = window.location.hash;
  if (!hash || !hash.startsWith('#r=')) {
    return null;
  }
  
  const fragment = hash.substring(3);
  return decodeReceiptFromFragment(fragment);
}
