/**
 * catalog.js - Catalog URL builder utility
 * Centralizes the logic for building catalog links
 */

/**
 * Build a catalog URL for a library item
 * Priority:
 * 1. Use record_url if available (contains full discovery URL)
 * 2. Build from alma_mms if available (use Primo permalink format)
 * 3. Return null if no identifiers available
 * 
 * @param {Object} item - Library item with catalog identifiers
 * @param {string} item.record_url - Full catalog URL (preferred)
 * @param {string} item.alma_mms - Alma MMS ID for building permalink
 * @returns {string|null} - Catalog URL or null if unavailable
 */
export function buildCatalogUrl(item) {
  // Priority 1: Use existing record_url if available
  if (item.record_url && typeof item.record_url === 'string' && item.record_url.trim()) {
    return item.record_url.trim();
  }
  
  // Priority 2: Build from alma_mms using Primo permalink format
  // This is the "old format" that was previously working
  if (item.alma_mms && typeof item.alma_mms === 'string' && item.alma_mms.trim()) {
    const mmsId = item.alma_mms.trim();
    // Use the Primo permalink format that integrates better with the discovery layer
    return `https://clark.primo.exlibrisgroup.com/permalink/01CLARKART_INST/1gqonkq/${mmsId}`;
  }
  
  // No valid identifiers
  return null;
}

/**
 * Build external search links for an item
 * @param {Object} item - Library item
 * @returns {Array<{label: string, href: string}>} - Array of external links
 */
export function buildExternalLinks(item) {
  const links = [];
  
  // Catalog link
  const catalogUrl = buildCatalogUrl(item);
  if (catalogUrl) {
    links.push({
      label: 'View in Catalog',
      href: catalogUrl
    });
  }
  
  // ISBN-based links
  const isbn = extractIsbn(item);
  if (isbn) {
    links.push({
      label: 'Search Amazon',
      href: `https://www.amazon.com/s?k=${isbn}`
    });
    links.push({
      label: 'Find near me (WorldCat)',
      href: `https://worldcat.org/search?q=bn%3A${isbn}`
    });
  } else {
    // Fallback to title-based search
    const query = encodeURIComponent(
      `${item.title || ''} ${Array.isArray(item.authors) ? item.authors.join(' ') : item.authors || ''}`.trim()
    );
    if (query && query !== encodeURIComponent('')) {
      links.push({
        label: 'Search Amazon',
        href: `https://www.amazon.com/s?k=${query}`
      });
      links.push({
        label: 'Find near me (WorldCat)',
        href: `https://worldcat.org/search?q=ti%3A${query}`
      });
    }
  }
  
  return links;
}

/**
 * Extract a clean ISBN-10/13 from item identifiers
 * @param {Object} item - Library item
 * @returns {string|null} - Clean ISBN or null
 */
function extractIsbn(item) {
  const candidates = [];
  
  // Check various possible ISBN fields
  const fields = [
    item.isbn,
    item.isbn_10,
    item.isbn_13,
    item.isbns,
    item.identifiers
  ];
  
  for (const field of fields) {
    if (!field) continue;
    
    if (Array.isArray(field)) {
      candidates.push(...field);
    } else if (typeof field === 'string') {
      // Split by pipe or comma
      candidates.push(...field.split(/[|,]/));
    }
  }
  
  // Find first valid ISBN (10 or 13 digits)
  for (const candidate of candidates) {
    if (!candidate) continue;
    const clean = String(candidate).replace(/[^0-9Xx]/g, '');
    if (clean.length === 10 || clean.length === 13) {
      return clean;
    }
  }
  
  return null;
}
