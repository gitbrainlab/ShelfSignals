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
  if (!yearRaw) return null;
  
  // Handle arrays
  let yearStr = yearRaw;
  if (Array.isArray(yearRaw)) {
    yearStr = yearRaw[0] || "";
  }
  
  // Convert to string
  yearStr = String(yearStr).trim();
  if (!yearStr) return null;
  
  // Remove common prefixes (c, ca, circa, etc.)
  yearStr = yearStr.replace(/^(c\.?|ca\.?|circa)\s*/i, "");
  
  // Extract first 4-digit year
  const match = yearStr.match(/\b(1\d{3}|20\d{2})\b/);
  if (match) {
    const year = parseInt(match[1], 10);
    // Sanity check: reasonable year range
    if (year >= 1000 && year <= 2100) {
      return year;
    }
  }
  
  return null;
}
