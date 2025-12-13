/**
 * year.js - Year normalization utility
 * Extracts primary year from messy date strings
 */

/**
 * Normalize a year string and extract primary year
 * @param {string|Array} yearRaw - Raw year data (e.g., "1935-1949", "c1990", ["1990"])
 * @returns {number|null} - Extracted year or null
 */
export function normalizeYear(yearRaw) {
  const FUTURE_YEAR_OFFSET = 50;
  if (!yearRaw) return null;

  let yearStr = yearRaw;
  if (Array.isArray(yearRaw)) {
    yearStr = yearRaw[0] || "";
  }

  yearStr = String(yearStr).trim();
  if (!yearStr) return null;

  // Remove common prefixes (c, ca, circa, between, etc.)
  yearStr = yearStr.replace(/^(c\.?|ca\.?|circa|between)\s*/i, "");

  // Capture all reasonable 4-digit years and pick the earliest as a primary anchor
  const MAX_YEAR = new Date().getFullYear() + FUTURE_YEAR_OFFSET;
  const matches = Array.from(yearStr.matchAll(/\b(1\d{3}|20\d{2})\b/g))
    .map(m => parseInt(m[1], 10))
    .filter(y => y >= 1000 && y <= MAX_YEAR);

  if (matches.length > 0) {
    return Math.min(...matches);
  }

  return null;
}
