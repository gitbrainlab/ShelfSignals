/**
 * signals.js - Centralized signals (theme) registry
 * Defines the canonical signal/theme labels, order, keywords, and colors
 */

export const SIGNALS = [
  {
    id: "image",
    label: "Image / media / cinema",
    color: "#1f77b4",
    legendStyle: "border-style:solid;",
    keywords: [
      /photograph/i, /photo\b/i, /camera/i, /cinema/i, /film\b/i, /motion picture/i,
      /documentary film/i, /visual/i, /media/i, /photojournalism/i
    ]
  },
  {
    id: "labor",
    label: "Labor / work / class",
    color: "#e15759",
    legendStyle: "border-style:dashed;",
    keywords: [
      /labor/i, /labour/i, /working class/i, /worker/i, /union/i, /strike/i,
      /factory/i, /industry/i, /industrial/i, /proletariat/i
    ]
  },
  {
    id: "capital",
    label: "Capital / empire",
    color: "#bcbd22",
    legendStyle: "border-width:3px;",
    keywords: [
      /capitalism/i, /socialism/i, /communism/i, /marx/i, /imperial/i, /empire/i,
      /colon/i, /neoliberal/i, /economic history/i, /political economy/i
    ]
  },
  {
    id: "sea",
    label: "Sea / ports / maritime",
    color: "#2ca02c",
    legendStyle: "border-radius:0;",
    keywords: [
      /harbor/i, /harbour/i, /port\b/i, /shipping/i, /dock/i, /maritime/i,
      /ocean/i, /sea\b/i, /seafaring/i, /naval/i, /merchant marine/i, /ship\b/i, /shipwreck/i
    ]
  },
  {
    id: "cities",
    label: "Cities / logistics",
    color: "#9467bd",
    legendStyle: "border-style:double;",
    keywords: [
      /los angeles/i, /urban/i, /city\b/i, /cities and towns/i, /metropolitan/i,
      /infrastructure/i, /transport/i, /railroad/i, /road/i, /logistic/i
    ]
  },
  {
    id: "war",
    label: "War / policing",
    color: "#8c564b",
    legendStyle: "border-style:solid;border-color:#999;",
    keywords: [
      /war/i, /military/i, /armed forces/i, /militarism/i, /police/i, /policing/i,
      /prison/i, /penal/i, /security/i, /surveillance/i
    ]
  },
  {
    id: "borders",
    label: "Borders / migration",
    color: "#17becf",
    legendStyle: "border-style:solid;border-color:#555;",
    keywords: [
      /emigration/i, /immigration/i, /migration/i, /refugee/i, /diaspora/i,
      /border/i, /citizenship/i
    ]
  },
  {
    id: "archives",
    label: "Archives / museums",
    color: "#7f7f7f",
    legendStyle: "border-style:solid;border-color:#777;",
    keywords: [
      /museum/i, /archive/i, /library/i, /collecting/i, /collection of/i, /exhibition/i, /institutions?/i
    ]
  },
  {
    id: "art",
    label: "Art / literature",
    color: "#d62728",
    legendStyle: "border-style:solid;border-color:#444;",
    keywords: [
      /art\b/i, /artist/i, /painting/i, /sculpture/i, /photography\b/i, /photography.*artistic/i,
      /fiction/i, /poetry/i, /drama/i, /literature/i
    ]
  },
  {
    id: "theory",
    label: "Theory / method",
    color: "#ff7f0e",
    legendStyle: "border-style:dotted;",
    keywords: [
      /philosophy/i, /theory/i, /aesthetic/i, /psychoanalys/i, /critical theory/i,
      /semiotic/i, /hermeneutic/i
    ]
  }
];

export const SIGNAL_IDS = SIGNALS.map(s => s.id);

export const SIGNAL_LABELS = SIGNALS.reduce((acc, signal) => {
  acc[signal.id] = signal.label;
  return acc;
}, {});

const SIGNAL_KEYWORDS = SIGNALS.reduce((acc, signal) => {
  acc[signal.id] = signal.keywords;
  return acc;
}, {});

/**
 * Derive signals from subjects and notes using the centralized registry
 */
export function deriveSignals(subjects = [], notes = []) {
  const candidates = [];

  if (Array.isArray(subjects)) {
    candidates.push(...subjects.filter(Boolean));
  } else if (subjects) {
    candidates.push(subjects);
  }

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
