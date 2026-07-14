/**
 * Copy-specific placement helpers for the Allan Sekula Library.
 *
 * Placement labels are transcribed from Clark provenance notes. Display text
 * is preserved; normalized keys exist only for deduplication and filtering.
 */

const IDENTIFIER_PATTERN = /Sekula\s+Library\s+Identifier\s*:\s*([^;]+)/gi;

// Two harvested notes contain catalog-system text after a valid Sekula box
// coordinate. Keep these corrections explicit and auditable instead of using
// a broad heuristic that could silently rewrite a real source label.
const AUDITED_SOURCE_LABEL_CORRECTIONS = new Map([
  ["Allan Studio Book Room Box A6 7102 Sterling and Francine Clark Art Institute. Library", "Allan Studio Book Room Box A6"],
  ["Allan Studio Book Room Box C5 5411 CAI copy 2", "Allan Studio Book Room Box C5"]
]);

const ROOM_GROUPS = [
  {
    label: "Allan Studio Book Room",
    pattern: /^(?:(?:allan|alan|allen)\s*(?:sekula\s+)?stu(?:dio|do|dion)\s+(?:(?:book|boor)\s+)?room(?=\b|shelf)|allanstudio\s+book\s+room)/i
  },
  { label: "Front Bedroom", pattern: /^front\s+bedroo+m\b/i },
  { label: "Garden Shed", pattern: /^garden\s*(?:shed|shelf)\b/i },
  { label: "Study", pattern: /^study\b/i },
  { label: "Bottom Front", pattern: /^bottom\s+front\b/i },
  { label: "Sally Living Room", pattern: /^sally(?:'s|\s*-\s*)?\s*living\s+room\b/i },
  { label: "Studio", pattern: /^studio\b/i }
];

// A source label occasionally records several placements in one field. Split
// only where a separator is followed by another explicit room/area name; a
// compact label such as "Study X & Y" remains exactly one source placement.
const EXPLICIT_ROOM_START = [
  String.raw`(?:(?:allan|alan|allen)\s*(?:sekula\s+)?stu(?:dio|do|dion)\s+(?:(?:book|boor)\s+)?room|allanstudio\s+book\s+room)`,
  String.raw`front\s+bedroo+m`,
  String.raw`garden\s*(?:shed|shelf)`,
  String.raw`study`,
  String.raw`bottom\s+front`,
  String.raw`sally(?:'s|\s*-\s*)?\s*(?:living\s+room|getty)`,
  String.raw`studio`
].join("|");
const EXPLICIT_PLACEMENT_SEPARATOR = new RegExp(
  String.raw`\s*(?:,|&|\band\b)\s*(?=(?:${EXPLICIT_ROOM_START})\b)`,
  "i"
);

function noteValues(value) {
  if (Array.isArray(value)) return value;
  return value == null || value === "" ? [] : [value];
}

function cleanPlacementLabel(value = "") {
  let label = String(value).normalize("NFKC").replace(/\s+/g, " ").trim();
  // Some source notes repeat the field label inside its own value.
  while (/^Sekula\s+Library\s+Identifier\s*:/i.test(label)) {
    label = label.replace(/^Sekula\s+Library\s+Identifier\s*:\s*/i, "").trim();
  }
  return label.replace(/^[,;:\s]+|[.;:\s]+$/g, "");
}

export function normalizePlacementKey(value = "") {
  return cleanPlacementLabel(value).toLocaleLowerCase("en-US");
}

export function roomForPlacement(value = "") {
  const label = cleanPlacementLabel(typeof value === "object" ? value?.label : value);
  if (!label) return { key: "", label: "" };
  const matched = ROOM_GROUPS.find(group => group.pattern.test(label));
  const roomLabel = matched?.label || label;
  return { key: normalizePlacementKey(roomLabel), label: roomLabel };
}

function splitPlacementLabel(value = "") {
  const label = cleanPlacementLabel(value);
  if (!label) return [];
  return label.split(EXPLICIT_PLACEMENT_SEPARATOR).map(cleanPlacementLabel).filter(Boolean);
}

function auditedPlacementLabel(value = "") {
  const sourceLabel = cleanPlacementLabel(value);
  const label = AUDITED_SOURCE_LABEL_CORRECTIONS.get(sourceLabel) || sourceLabel;
  return {
    label,
    sourceLabel,
    warnings: label === sourceLabel ? [] : ["audited_trailing_catalog_text_removed"]
  };
}

export function parsePhysicalIdentifiers(record = {}) {
  const placements = new Map();
  const fields = [
    ["provenance_notes", noteValues(record.provenance_notes)],
    ["sekula_notes", noteValues(record.sekula_notes)]
  ];

  for (const [field, notes] of fields) {
    notes.forEach((note, noteIndex) => {
      const text = String(note);
      let identifierIndex = 0;
      for (const match of text.matchAll(IDENTIFIER_PATTERN)) {
        splitPlacementLabel(match[1]).forEach((segment, segmentIndex) => {
          const corrected = auditedPlacementLabel(segment);
          const { label } = corrected;
          const key = normalizePlacementKey(label);
          if (!key) return;
          const source = {
            field,
            noteIndex,
            identifierIndex,
            segmentIndex,
            ...(corrected.warnings.length ? { sourceLabel: corrected.sourceLabel, warnings: corrected.warnings } : {})
          };
          const existing = placements.get(key);
          if (existing) {
            existing.sources.push(source);
            return;
          }
          const room = roomForPlacement(label);
          placements.set(key, {
            key,
            label,
            roomKey: room.key,
            roomLabel: room.label,
            sources: [source]
          });
        });
        identifierIndex += 1;
      }
    });
  }

  return [...placements.values()];
}

export function groupPlacementsByRoom(placements = []) {
  const groups = new Map();
  for (const placement of Array.isArray(placements) ? placements : []) {
    if (!placement?.key || !placement?.label) continue;
    const room = placement.roomKey && placement.roomLabel
      ? { key: placement.roomKey, label: placement.roomLabel }
      : roomForPlacement(placement.label);
    if (!room.key) continue;
    if (!groups.has(room.key)) groups.set(room.key, { key: room.key, label: room.label, placements: [] });
    groups.get(room.key).placements.push(placement);
  }
  return [...groups.values()];
}

export function recordMatchesPlacement(record = {}, selected = "") {
  const selectedKey = normalizePlacementKey(selected);
  if (!selectedKey) return true;
  const placements = Array.isArray(record.placements)
    ? record.placements
    : parsePhysicalIdentifiers(record);
  return placements.some(placement => normalizePlacementKey(placement?.key || placement?.label) === selectedKey);
}
