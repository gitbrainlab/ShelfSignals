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
  if (!callNumber || typeof callNumber !== 'string') {
    return { lcClass: null, lcNumber: null, lcKey: null };
  }
  
  const trimmed = callNumber.trim();
  if (!trimmed) {
    return { lcClass: null, lcNumber: null, lcKey: null };
  }
  
  // Match LC pattern: Letter(s) followed by number
  // Examples: "N", "NE", "NE2610", "NE2610 .U7"
  const match = trimmed.match(/^([A-Z]{1,3})(\d+(?:\.\d+)?)?/i);
  
  if (!match) {
    return { lcClass: null, lcNumber: null, lcKey: null };
  }
  
  const lcClass = match[1].toUpperCase();
  const lcNumber = match[2] ? parseFloat(match[2]) : null;
  
  // Generate sorting key: class + zero-padded number
  let lcKey = lcClass;
  if (lcNumber !== null) {
    // Pad number to 8 digits for sorting
    lcKey += String(Math.floor(lcNumber)).padStart(8, '0');
  }
  
  return { lcClass, lcNumber, lcKey };
}
