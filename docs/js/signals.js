/**
 * signals.js - Centralized signals (theme) registry
 * Defines the canonical signal/theme labels, order, and keyword patterns
 */

export const SIGNAL_ORDER = [
  "image",
  "labor",
  "capital",
  "sea",
  "cities",
  "war",
  "borders",
  "archives",
  "art",
  "theory"
];

export const SIGNAL_LABELS = {
  image: "Image",
  labor: "Labor",
  capital: "Capital",
  sea: "Sea",
  cities: "Cities",
  war: "War",
  borders: "Borders",
  archives: "Archives",
  art: "Art",
  theory: "Theory"
};

export const SIGNAL_KEYWORDS = {
  image: [
    /photograph/i, /photo\b/i, /camera/i, /cinema/i, /film\b/i, /motion picture/i,
    /documentary film/i, /visual/i, /media/i, /photojournalism/i
  ],
  labor: [
    /labor/i, /labour/i, /working class/i, /worker/i, /union/i, /strike/i,
    /factory/i, /industry/i, /industrial/i, /proletariat/i
  ],
  capital: [
    /capitalism/i, /socialism/i, /communism/i, /marx/i, /imperial/i, /empire/i,
    /colon/i, /neoliberal/i, /economic history/i, /political economy/i
  ],
  sea: [
    /harbor/i, /harbour/i, /port\b/i, /shipping/i, /dock/i, /maritime/i,
    /ocean/i, /sea\b/i, /seafaring/i, /naval/i, /merchant marine/i, /ship\b/i, /shipwreck/i
  ],
  cities: [
    /los angeles/i, /urban/i, /city\b/i, /cities and towns/i, /metropolitan/i,
    /infrastructure/i, /transport/i, /railroad/i, /road/i, /logistic/i
  ],
  war: [
    /war/i, /military/i, /armed forces/i, /militarism/i, /police/i, /policing/i,
    /prison/i, /penal/i, /security/i, /surveillance/i
  ],
  borders: [
    /emigration/i, /immigration/i, /migration/i, /refugee/i, /diaspora/i,
    /border/i, /citizenship/i
  ],
  archives: [
    /museum/i, /archive/i, /library/i, /collecting/i, /collection of/i, /exhibition/i, /institutions?/i
  ],
  art: [
    /art\b/i, /artist/i, /painting/i, /sculpture/i, /photography, artistic/i,
    /fiction/i, /poetry/i, /drama/i, /literature/i
  ],
  theory: [
    /philosophy/i, /theory/i, /aesthetic/i, /psychoanalys/i, /critical theory/i,
    /semiotic/i, /hermeneutic/i
  ]
};

/**
 * Derive signals from subjects and notes
 */
export function deriveSignals(subjects = [], notes = []) {
  const candidates = [];
  
  // Flatten subjects
  if (Array.isArray(subjects)) {
    candidates.push(...subjects.filter(Boolean));
  } else if (subjects) {
    candidates.push(subjects);
  }
  
  // Flatten notes
  if (Array.isArray(notes)) {
    candidates.push(...notes.filter(Boolean));
  } else if (notes) {
    candidates.push(notes);
  }
  
  const haystack = candidates.join(" | ");
  const signals = new Set();
  
  for (const [signal, patterns] of Object.entries(SIGNAL_KEYWORDS)) {
    if (patterns.some(re => re.test(haystack))) {
      signals.add(signal);
    }
  }
  
  return Array.from(signals);
}
