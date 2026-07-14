/**
 * spatial.js - Static spatial model helpers for ShelfSignals Preview.
 *
 * Pure functions only: deterministic, testable, and safe for static hosting.
 */

import { parsePhysicalIdentifiers } from "./placement.js";

export const DEFAULT_SPATIAL_CONFIG = {
  walls: [
    {
      id: "east",
      label: "East Wall",
      zones: [
        { id: "E1", label: "East Wall E1", sRange: [1, 1800] },
        { id: "E2", label: "East Wall E2", sRange: [1801, 3600] },
        { id: "E3", label: "East Wall E3", sRange: [3601, 5400] }
      ]
    },
    {
      id: "west",
      label: "West Wall",
      zones: [
        { id: "W1", label: "West Wall W1", sRange: [5401, 7200] },
        { id: "W2", label: "West Wall W2", sRange: [7201, 9000] },
        { id: "W3", label: "West Wall W3", sRange: [9001, 10800] },
        { id: "W4", label: "West Wall W4", sRange: [10801, 15000] }
      ]
    }
  ],
  clusters: [
    { id: "A", label: "Cluster A", sRange: [1, 1500] },
    { id: "B", label: "Cluster B", sRange: [1501, 3000] },
    { id: "C", label: "Cluster C", sRange: [3001, 4500] },
    { id: "D", label: "Cluster D", sRange: [4501, 6000] },
    { id: "E", label: "Cluster E", sRange: [6001, 7500] },
    { id: "F", label: "Cluster F", sRange: [7501, 9000] },
    { id: "G", label: "Cluster G", sRange: [9001, 10500] },
    { id: "H", label: "Cluster H", sRange: [10501, 12000] },
    { id: "I", label: "Cluster I", sRange: [12001, 13500] },
    { id: "J", label: "Cluster J", sRange: [13501, 15000] }
  ]
};

export function parseSNumber(callNumber = "") {
  const text = String(callNumber || "");
  // Clark's Sekula shelf identifier is the five-digit suffix following the
  // collection cutter. Do not treat ordinary .S43 cutters or publication
  // years as physical shelf positions.
  const collectionMark = text.match(/\bNE\s*2698\s+\.S4637L\s+0*(\d{1,5})\b/i);
  if (collectionMark) return Number(collectionMark[1]);

  // Explicit S-number labels may occur in annotations and remain safe to parse.
  const explicit = text.match(/(?:\bS(?=\s*[-:#]\s*\d)|\bS-number|\bSekula(?:\s+Library)?(?:\s+(?:number|no\.?|identifier))?)\s*[:#-]\s*0*(\d{1,5})\b/i);
  if (explicit) return Number(explicit[1]);

  return null;
}

export function parsePhysicalIdentifier(record = {}) {
  return parsePhysicalIdentifiers(record)[0]?.label || "";
}

function inRange(value, range) {
  return Number.isFinite(value) && Array.isArray(range) && value >= range[0] && value <= range[1];
}

export function resolveSpatialPosition(record = {}, config = DEFAULT_SPATIAL_CONFIG) {
  const sNumber = parseSNumber(record.call_number);
  const physicalIdentifier = parsePhysicalIdentifier(record);
  let wall = null;
  let zone = null;
  let cluster = null;

  for (const candidateWall of config.walls || []) {
    for (const candidateZone of candidateWall.zones || []) {
      if (inRange(sNumber, candidateZone.sRange)) {
        wall = candidateWall;
        zone = candidateZone;
        break;
      }
    }
    if (zone) break;
  }

  for (const candidateCluster of config.clusters || []) {
    if (inRange(sNumber, candidateCluster.sRange)) {
      cluster = candidateCluster;
      break;
    }
  }

  return {
    sNumber,
    physicalIdentifier,
    wallId: wall?.id || "unmapped",
    wallLabel: wall?.label || "Unmapped Wall",
    zoneId: zone?.id || "unmapped",
    zoneLabel: zone?.label || "Unmapped Zone",
    clusterId: cluster?.id || "unmapped",
    clusterLabel: cluster?.label || "Unmapped Cluster",
    rangeLabel: sNumber ? `S${String(sNumber).padStart(5, "0")}` : "No S-number"
  };
}

export function spatialGroupKey(item = {}, groupBy = "lc") {
  if (groupBy === "wall") return item.spatial?.wallLabel || "Unmapped Wall";
  if (groupBy === "zone") return item.spatial?.zoneLabel || "Unmapped Zone";
  if (groupBy === "cluster") return item.spatial?.clusterLabel || "Unmapped Cluster";
  if (groupBy === "physical") return item.spatial?.physicalIdentifier || "Unplaced";
  return item.lcClass || "Other";
}

export function computeSignalEvidence(record = {}, signals = [], registry = []) {
  const fields = [
    ["subjects", record.subjects],
    ["notes", record.sekula_notes],
    ["provenance", record.provenance_notes],
    ["title", record.title],
    ["description", record.description],
    ["contents", record.table_of_contents]
  ];
  const signalMap = new Map(registry.map(signal => [signal.id, signal]));

  return signals.reduce((acc, signalId) => {
    const signal = signalMap.get(signalId);
    const hits = [];
    if (!signal) {
      acc[signalId] = hits;
      return acc;
    }

    for (const [field, value] of fields) {
      const values = Array.isArray(value) ? value : (value ? [value] : []);
      for (const candidate of values) {
        const text = String(candidate);
        for (const pattern of signal.keywords || []) {
          pattern.lastIndex = 0;
          if (pattern.test(text)) {
            hits.push({ field, evidence: text.slice(0, 180), pattern: String(pattern) });
            break;
          }
        }
        if (hits.length >= 4) break;
      }
      if (hits.length >= 4) break;
    }
    acc[signalId] = hits;
    return acc;
  }, {});
}

export function computeSignalOverlaps(items = [], limit = 12) {
  const counts = new Map();
  for (const item of items) {
    const signals = [...new Set(item.signals || [])].sort();
    for (let i = 0; i < signals.length; i++) {
      for (let j = i + 1; j < signals.length; j++) {
        const key = `${signals[i]}+${signals[j]}`;
        counts.set(key, (counts.get(key) || 0) + 1);
      }
    }
  }
  return Array.from(counts.entries())
    .map(([key, count]) => {
      const [a, b] = key.split("+");
      return { signals: [a, b], count };
    })
    .sort((a, b) => b.count - a.count || a.signals.join("+").localeCompare(b.signals.join("+")))
    .slice(0, limit);
}

export function spatialDiagnostics(items = []) {
  const total = items.length;
  const withSNumber = items.filter(item => Number.isFinite(item.spatial?.sNumber)).length;
  const withPhysicalIdentifier = items.filter(item => item.spatial?.physicalIdentifier).length;
  const unmapped = items.filter(item => item.spatial?.zoneId === "unmapped").length;
  const duplicateSNumbers = new Map();

  for (const item of items) {
    const sNumber = item.spatial?.sNumber;
    if (Number.isFinite(sNumber)) {
      duplicateSNumbers.set(sNumber, (duplicateSNumbers.get(sNumber) || 0) + 1);
    }
  }

  return {
    total,
    withSNumber,
    withPhysicalIdentifier,
    unmapped,
    duplicateSNumberCount: Array.from(duplicateSNumbers.values()).filter(count => count > 1).length,
    sNumberCoverage: total ? withSNumber / total : 0,
    physicalCoverage: total ? withPhysicalIdentifier / total : 0
  };
}

export function buildReceiptAnnotations({ groupBy = "lc", activePath = null, printMode = null, diagnostics = null } = {}) {
  return {
    spatialModel: "clark-reading-room@1",
    groupBy,
    activePath: activePath ? { id: activePath.id, label: activePath.label } : null,
    printMode,
    diagnostics
  };
}
