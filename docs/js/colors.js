/**
 * colors.js - Unified color logic
 * Provides color palettes and spine color assignment
 */
import { SIGNALS } from "./signals.js";

// Default color palette
const DEFAULT_PALETTE = {
  N: "#8B4513",    // Saddle Brown
  Q: "#2E8B57",    // Sea Green
  T: "#4682B4",    // Steel Blue
  P: "#9370DB",    // Medium Purple
  B: "#CD853F",    // Peru
  H: "#DC143C",    // Crimson
  D: "#FF8C00",    // Dark Orange
  G: "#20B2AA",    // Light Sea Green
  J: "#6A5ACD",    // Slate Blue
  K: "#FF6347",    // Tomato
  L: "#32CD32",    // Lime Green
  M: "#FF69B4",    // Hot Pink
  R: "#1E90FF",    // Dodger Blue
  S: "#FFD700",    // Gold
  U: "#00CED1",    // Dark Turquoise
  V: "#FF4500",    // Orange Red
  Z: "#9932CC"     // Dark Orchid
};

// Colorblind-friendly palette (based on Wong's palette and similar)
const COLORBLIND_PALETTE = {
  N: "#D55E00",    // Vermillion
  Q: "#009E73",    // Bluish Green
  T: "#0072B2",    // Blue
  P: "#CC79A7",    // Reddish Purple
  B: "#E69F00",    // Orange
  H: "#F0E442",    // Yellow
  D: "#56B4E9",    // Sky Blue
  G: "#009E73",    // Bluish Green
  J: "#0072B2",    // Blue
  K: "#D55E00",    // Vermillion
  L: "#009E73",    // Bluish Green
  M: "#CC79A7",    // Reddish Purple
  R: "#56B4E9",    // Sky Blue
  S: "#F0E442",    // Yellow
  U: "#0072B2",    // Blue
  V: "#D55E00",    // Vermillion
  Z: "#CC79A7"     // Reddish Purple
};

const PALETTES = {
  default: {
    label: "Default",
    colors: DEFAULT_PALETTE
  },
  colorblind: {
    label: "Colorblind-Friendly",
    colors: COLORBLIND_PALETTE
  }
};

const SIGNAL_COLOR_MAP = SIGNALS.reduce((acc, signal) => {
  acc[signal.id] = signal.color;
  return acc;
}, {});

// Storage key for palette preference
const STORAGE_KEY = "shelfsignals_palette";

/**
 * Get the active palette configuration from localStorage or default
 */
export function getActivePalette() {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored && PALETTES[stored] ? stored : "default";
}

/**
 * Set the active palette and persist to localStorage
 */
export function setActivePalette(paletteKey) {
  if (!PALETTES[paletteKey]) {
    paletteKey = "default";
  }
  localStorage.setItem(STORAGE_KEY, paletteKey);
  return paletteKey;
}

/**
 * Get spine color based on mode and palette
 * @param {string} mode - "lc_class" or "signals"
 * @param {Object} options - { lcClass, signalId, zone, paletteKey }
 * @returns {string} - CSS color string
 */
export function getSpineColor(mode = "signals", { lcClass = null, signalId = null, zone = null, paletteKey = null } = {}) {
  if (mode === "lc_class" && lcClass) {
    const palette = PALETTES[paletteKey || getActivePalette()];
    const firstLetter = lcClass.charAt(0).toUpperCase();
    return (palette.colors[firstLetter] || "#999");
  }

  if (mode === "signals" && signalId) {
    return SIGNAL_COLOR_MAP[signalId] || "#1f77b4";
  }

  // Default zone colors (from original)
  const zoneColors = {
    "Front Bedroom": "#ff7f0e",
    "Middle Bedroom": "#2ca02c",
    "Back Bedroom": "#d62728",
    "Guest Bedroom": "#9467bd",
    "Front Office": "#8c564b",
    "Back Office": "#e377c2"
  };

  if (mode === "zone" && zone) {
    return zoneColors[zone] || "#1f77b4";
  }

  return "#ccc";
}

/**
 * Get all available palettes
 */
export function getPalettes() {
  return PALETTES;
}
