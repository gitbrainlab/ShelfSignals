/**
 * exhibition.js - Static exhibition cycle, presence token, and voting helpers.
 *
 * The prototype stores presence tokens and votes in browser localStorage, but
 * keeps all rules deterministic so a later minting or server adapter can reuse
 * the same schemas.
 */

export const DEFAULT_VOTE_OPTIONS = {
  signals: [
    { id: "image", label: "Photography" },
    { id: "labor", label: "Labor" },
    { id: "sea", label: "Maritime" },
    { id: "archives", label: "Archive" },
    { id: "capital", label: "Capital" },
    { id: "cities", label: "City" },
    { id: "war", label: "War" },
    { id: "theory", label: "Theory" }
  ],
  overlaps: [
    { id: "image+labor", signals: ["image", "labor"], label: "Photography x Labor" },
    { id: "capital+sea", signals: ["capital", "sea"], label: "Maritime x Capital" },
    { id: "archives+image", signals: ["archives", "image"], label: "Archive x Image" },
    { id: "archives+capital", signals: ["archives", "capital"], label: "Archive x Institution" },
    { id: "cities+capital", signals: ["cities", "capital"], label: "City x Infrastructure" },
    { id: "image+war", signals: ["image", "war"], label: "War x Image" },
    { id: "art+theory", signals: ["art", "theory"], label: "Theory x Aesthetics" },
    { id: "borders+cities", signals: ["borders", "cities"], label: "Border x Migration" }
  ],
  zones: [
    { id: "E1", label: "East Wall E1" },
    { id: "E2", label: "East Wall E2" },
    { id: "E3", label: "East Wall E3" },
    { id: "W1", label: "West Wall W1" },
    { id: "W2", label: "West Wall W2" },
    { id: "W3", label: "West Wall W3" },
    { id: "W4", label: "West Wall W4" }
  ],
  visualBehaviors: [
    { id: "signal_overlaps", label: "Show signal overlaps" },
    { id: "logistics_clusters", label: "Reveal logistics clusters" },
    { id: "expand_dense_clusters", label: "Expand dense clusters" },
    { id: "reveal_outliers", label: "Reveal outliers" },
    { id: "chronology", label: "Emphasize chronology" },
    { id: "trace_provenance", label: "Trace provenance" },
    { id: "map_shelf_gaps", label: "Map shelf gaps" },
    { id: "constellation", label: "Constellation view" }
  ],
  outputs: [
    { id: "reading_list", label: "Printed reading list" },
    { id: "wall_map", label: "Wall map" },
    { id: "projection_sequence", label: "Projection sequence" },
    { id: "label_set", label: "Label set" },
    { id: "public_receipt", label: "Public digital receipt" },
    { id: "curator_handout", label: "Curator handout" }
  ]
};

export function normalizeOverlapKey(value = []) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).slice().sort().join("+");
  }
  return String(value || "")
    .split("+")
    .map(part => part.trim())
    .filter(Boolean)
    .sort()
    .join("+");
}

export function labelForOption(kind, id, options = DEFAULT_VOTE_OPTIONS) {
  const list = options[kind] || [];
  const option = list.find(candidate => candidate.id === id);
  return option?.label || id || "";
}

export function labelForSignals(signals = [], options = DEFAULT_VOTE_OPTIONS) {
  return signals
    .map(signal => labelForOption("signals", signal, options))
    .filter(Boolean)
    .join(" x ");
}

export function getActiveCycle(config = {}, now = new Date()) {
  const cycles = config.cycles || [];
  if (config.current_cycle_id) {
    const configured = cycles.find(cycle => cycle.cycle_id === config.current_cycle_id);
    if (configured) return configured;
  }

  const time = now instanceof Date ? now : new Date(now);
  const timed = cycles.find(cycle => {
    if (cycle.status !== "active") return false;
    const starts = cycle.starts_at ? new Date(cycle.starts_at) : null;
    const ends = cycle.ends_at ? new Date(cycle.ends_at) : null;
    return (!starts || starts <= time) && (!ends || time <= ends);
  });

  return timed || cycles.find(cycle => cycle.status === "active") || cycles[0] || null;
}

export function nextPresenceSequence(tokens = [], votes = [], cycle = {}) {
  const seen = new Set();
  for (const token of tokens || []) {
    if (token?.token_id) seen.add(token.token_id);
  }
  for (const vote of votes || []) {
    if (vote?.token_id) seen.add(vote.token_id);
  }
  const base = Number(cycle.vote_count || 0);
  return base + seen.size + 1;
}

export function createPresenceToken({
  cycleId,
  claimedAt = new Date().toISOString(),
  sequence = 1,
  claimMethod = "walletless",
  walletAddress = null
} = {}) {
  if (!cycleId) {
    throw new Error("createPresenceToken requires a cycleId");
  }

  const year = String(claimedAt).slice(0, 4) || String(new Date().getUTCFullYear());
  const padded = String(Math.max(1, Number(sequence) || 1)).padStart(6, "0");
  const token = {
    token_id: `presence-${year}-${padded}`,
    type: "presence_token",
    cycle_id: cycleId,
    claimed_at: claimedAt,
    eligible_to_vote: true,
    has_voted: false,
    claim_method: claimMethod
  };

  if (claimMethod === "wallet") {
    token.wallet_address = walletAddress;
  }

  return token;
}

export function findTokenForCycle(tokens = [], cycleId) {
  return (tokens || []).find(token => token?.cycle_id === cycleId && token?.type === "presence_token") || null;
}

export function tokenHasVoted(token = {}, votes = [], cycleId = token?.cycle_id) {
  if (token?.has_voted) return true;
  return (votes || []).some(vote => vote?.token_id === token?.token_id && vote?.cycle_id === cycleId);
}

export function isPresenceTokenEligible(token = {}, cycle = {}, votes = []) {
  if (!token || !cycle) return false;
  return token.type === "presence_token" &&
    token.cycle_id === cycle.cycle_id &&
    token.eligible_to_vote === true &&
    !tokenHasVoted(token, votes, cycle.cycle_id);
}

export function createVote({
  token,
  cycle,
  selections = {},
  castAt = new Date().toISOString()
} = {}) {
  if (!token?.token_id) {
    throw new Error("createVote requires a presence token");
  }
  if (!cycle?.cycle_id) {
    throw new Error("createVote requires a cycle");
  }

  const overlapKey = normalizeOverlapKey(selections.selected_overlap);
  const tokenParts = token.token_id.split("-");
  const sequence = tokenParts[tokenParts.length - 1] || "000001";

  return {
    vote_id: `vote-${cycle.cycle_id.replace("cycle-", "")}-${sequence}`,
    token_id: token.token_id,
    cycle_id: cycle.cycle_id,
    selected_signal: selections.selected_signal || null,
    selected_overlap: overlapKey ? overlapKey.split("+") : [],
    selected_zone: selections.selected_zone || null,
    selected_visual_behavior: selections.selected_visual_behavior || null,
    selected_output: selections.selected_output || null,
    cast_at: castAt
  };
}

function countVotes(votes, allowedIds, selector) {
  const allowed = new Set(allowedIds);
  const counts = new Map(allowedIds.map(id => [id, 0]));

  for (const vote of votes || []) {
    const id = selector(vote);
    if (allowed.has(id)) {
      counts.set(id, (counts.get(id) || 0) + 1);
    }
  }

  return allowedIds
    .map((id, order) => ({ id, count: counts.get(id) || 0, order }))
    .sort((a, b) => b.count - a.count || a.order - b.order);
}

function winningOption(votes, options, selector, fallbackId = null) {
  const orderedIds = options.map(option => option.id);
  const ranked = countVotes(votes, orderedIds, selector);
  const winner = ranked[0] || { id: fallbackId, count: 0 };
  if (!winner.id && fallbackId) return { id: fallbackId, count: 0, ranked };
  return { ...winner, ranked };
}

export function tallyVotes(votes = [], currentCycle = {}, options = DEFAULT_VOTE_OPTIONS) {
  const cycleVotes = votes.filter(vote => vote.cycle_id === currentCycle.cycle_id);
  const fallbackSignal = currentCycle.active_signals?.[0] || options.signals[0]?.id || null;
  const fallbackOverlap = normalizeOverlapKey(currentCycle.active_signals || []) || options.overlaps[0]?.id || null;
  const fallbackZone = currentCycle.active_zones?.[0] || options.zones[0]?.id || null;
  const fallbackBehavior = currentCycle.visual_behavior || options.visualBehaviors[0]?.id || null;
  const fallbackOutput = currentCycle.public_output || options.outputs[0]?.id || null;

  const signal = winningOption(cycleVotes, options.signals, vote => vote.selected_signal, fallbackSignal);
  const overlap = winningOption(cycleVotes, options.overlaps, vote => normalizeOverlapKey(vote.selected_overlap), fallbackOverlap);
  const zone = winningOption(cycleVotes, options.zones, vote => vote.selected_zone, fallbackZone);
  const visualBehavior = winningOption(cycleVotes, options.visualBehaviors, vote => vote.selected_visual_behavior, fallbackBehavior);
  const output = winningOption(cycleVotes, options.outputs, vote => vote.selected_output, fallbackOutput);
  const overlapOption = options.overlaps.find(option => option.id === overlap.id);

  return {
    cycle_id: currentCycle.cycle_id,
    vote_count: cycleVotes.length,
    winning_signal: signal,
    winning_overlap: {
      ...overlap,
      signals: overlapOption?.signals || (overlap.id ? overlap.id.split("+") : [])
    },
    winning_zone: zone,
    winning_visual_behavior: visualBehavior,
    winning_output: output
  };
}

function addDays(value, days) {
  const date = new Date(value);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString();
}

export function buildNextCycleConfig(currentCycle = {}, tally = {}, options = DEFAULT_VOTE_OPTIONS) {
  const currentNumber = Number(String(currentCycle.cycle_id || "").match(/\d+/)?.[0] || 0);
  const nextNumber = String(currentNumber + 1).padStart(3, "0");
  const activeSignals = tally.winning_overlap?.signals?.length
    ? tally.winning_overlap.signals
    : [tally.winning_signal?.id || currentCycle.active_signals?.[0]].filter(Boolean);
  const startsAt = currentCycle.ends_at || new Date().toISOString();
  const overlapLabel = labelForOption("overlaps", tally.winning_overlap?.id, options);
  const title = overlapLabel || labelForSignals(activeSignals, options) || `Cycle ${nextNumber}`;

  return {
    cycle_id: `cycle-${nextNumber}`,
    title,
    status: "generated",
    starts_at: startsAt,
    ends_at: addDays(startsAt, 7),
    active_signals: activeSignals,
    active_zones: [tally.winning_zone?.id || currentCycle.active_zones?.[0]].filter(Boolean),
    visual_behavior: tally.winning_visual_behavior?.id || currentCycle.visual_behavior || null,
    public_output: tally.winning_output?.id || currentCycle.public_output || null,
    vote_count: tally.vote_count || 0,
    source_cycle_id: currentCycle.cycle_id,
    winner: {
      signal: tally.winning_signal?.id || null,
      overlap: activeSignals,
      zone: tally.winning_zone?.id || null,
      visual_behavior: tally.winning_visual_behavior?.id || null,
      output: tally.winning_output?.id || null
    }
  };
}

function itemMatchesSignals(item, signals, requireAll = true) {
  if (!signals?.length) return true;
  const itemSignals = new Set(item.signals || []);
  return requireAll
    ? signals.every(signal => itemSignals.has(signal))
    : signals.some(signal => itemSignals.has(signal));
}

function itemMatchesZones(item, zones) {
  if (!zones?.length) return true;
  return zones.includes(item.spatial?.zoneId);
}

export function getCycleFilteredItems(items = [], cycle = {}) {
  const signals = cycle.active_signals || [];
  const zones = cycle.active_zones || [];
  const strict = items.filter(item => itemMatchesSignals(item, signals, true) && itemMatchesZones(item, zones));
  if (strict.length) return strict;

  const signalOnly = items.filter(item => itemMatchesSignals(item, signals, true));
  if (signalOnly.length) return signalOnly;

  const relaxedSignals = items.filter(item => itemMatchesSignals(item, signals, false) && itemMatchesZones(item, zones));
  if (relaxedSignals.length) return relaxedSignals;

  return items.filter(item => itemMatchesZones(item, zones));
}

export function rankZonesBySignalDensity(items = [], signals = []) {
  const zones = new Map();
  for (const item of items) {
    const zoneId = item.spatial?.zoneId;
    if (!zoneId || zoneId === "unmapped") continue;
    if (!itemMatchesSignals(item, signals, signals.length > 1)) continue;

    const current = zones.get(zoneId) || {
      zone_id: zoneId,
      zone_label: item.spatial?.zoneLabel || zoneId,
      count: 0
    };
    current.count += 1;
    zones.set(zoneId, current);
  }

  return Array.from(zones.values())
    .sort((a, b) => b.count - a.count || a.zone_id.localeCompare(b.zone_id));
}

export function buildParticipationAnnotations({
  token = null,
  vote = null,
  cycle = null,
  shelf = []
} = {}) {
  return {
    exhibition: {
      title: "ShelfSignals: A Library That Changes When You Visit",
      cycle_id: cycle?.cycle_id || token?.cycle_id || vote?.cycle_id || null,
      cycle_title: cycle?.title || null,
      active_signals: cycle?.active_signals || [],
      active_zones: cycle?.active_zones || []
    },
    presence: token ? {
      token_id: token.token_id,
      type: token.type,
      claimed_at: token.claimed_at,
      claim_method: token.claim_method,
      eligible_to_vote: token.eligible_to_vote,
      has_voted: token.has_voted
    } : null,
    vote: vote ? {
      vote_id: vote.vote_id,
      selected_signal: vote.selected_signal,
      selected_overlap: vote.selected_overlap,
      selected_zone: vote.selected_zone,
      selected_visual_behavior: vote.selected_visual_behavior,
      selected_output: vote.selected_output,
      cast_at: vote.cast_at
    } : null,
    shelfTrail: shelf.map(item => ({
      id: item.id,
      title: item.title,
      signals: item.signals || []
    }))
  };
}
