/**
 * lc.js - LC call-number parser
 * Extracts LC class, number, and generates sorting key
 */

/**
 * Parse an LC call number string
 * @param {string} callNumber - LC call number (e.g., "NE2610 .U7")
 * @returns {Object} - { lcClass, lcNumber, lcKey }
 */
export function parseLcCallNumber(callNumber) {
  if (!callNumber || typeof callNumber !== "string") {
    return { lcClass: null, lcNumber: null, lcKey: null };
  }

  const trimmed = callNumber.trim();
  if (!trimmed) {
    return { lcClass: null, lcNumber: null, lcKey: null };
  }

  // Capture leading class letters and first numeric chunk
  const match = trimmed.match(/^([A-Za-z]{1,3})\s*([0-9]+(?:\.[0-9]+)?)?/);
  const lcClass = match ? match[1].toUpperCase() : null;

  // Fallback: find any letter cluster if the start was messy
  const fallbackClass = trimmed.match(/^[A-Za-z]{1,3}/);
  const finalClass = lcClass || (fallbackClass ? fallbackClass[0].toUpperCase() : null);

  const numericPart = match && match[2] ? match[2] : null;
  const lcNumber = numericPart ? parseFloat(numericPart) : null;

  // Generate sorting key: class + zero-padded integer part
  let lcKey = finalClass;
  if (lcNumber !== null && Number.isFinite(lcNumber)) {
    lcKey = (finalClass || "ZZZ") + String(Math.floor(lcNumber)).padStart(8, "0");
  }

  return { lcClass: finalClass, lcNumber, lcKey };
}
