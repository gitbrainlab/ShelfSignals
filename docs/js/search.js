/**
 * search.js - Debounced search state and match computation
 * Handles search query, debouncing, and match counting
 */

/**
 * Create a debounced function
 */
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * Search state manager
 */
export class SearchState {
  constructor() {
    this.query = "";
    this.listeners = new Set();
  }
  
  /**
   * Set search query and notify listeners (debounced)
   */
  setQuery(query, immediate = false) {
    this.query = query.trim().toLowerCase();
    
    if (immediate) {
      this.notify();
    } else {
      if (!this._debouncedNotify) {
        this._debouncedNotify = debounce(() => this.notify(), 300);
      }
      this._debouncedNotify();
    }
  }
  
  /**
   * Clear search query
   */
  clear() {
    this.setQuery("", true);
  }
  
  /**
   * Add a listener
   */
  addListener(callback) {
    this.listeners.add(callback);
  }
  
  /**
   * Remove a listener
   */
  removeListener(callback) {
    this.listeners.delete(callback);
  }
  
  /**
   * Notify all listeners
   */
  notify() {
    this.listeners.forEach(callback => callback(this.query));
  }
  
  /**
   * Check if a record matches the search query
   * @param {Object} record - Data record with searchable fields
   * @returns {Object} - { matches: boolean, matchCount: number, segments: Array }
   */
  computeMatch(record) {
    if (!this.query) {
      return { matches: true, matchCount: 0, segments: [] };
    }
    
    const fields = [
      { name: "title", value: record.title || "" },
      { name: "authors", value: Array.isArray(record.authors) ? record.authors.join(" ") : (record.authors || "") },
      { name: "subjects", value: Array.isArray(record.subjects) ? record.subjects.join(" ") : (record.subjects || "") },
      { name: "sekula_notes", value: Array.isArray(record.sekula_notes) ? record.sekula_notes.join(" ") : (record.sekula_notes || "") }
    ];
    
    let matchCount = 0;
    const segments = [];
    
    for (const field of fields) {
      const lowerValue = field.value.toLowerCase();
      if (lowerValue.includes(this.query)) {
        matchCount++;
        segments.push(field.name);
      }
    }
    
    return {
      matches: matchCount > 0,
      matchCount,
      segments
    };
  }
  
  /**
   * Get current query
   */
  getQuery() {
    return this.query;
  }
  
  /**
   * Check if search is active
   */
  isActive() {
    return this.query.length > 0;
  }
}

// Export singleton instance
export const searchState = new SearchState();
