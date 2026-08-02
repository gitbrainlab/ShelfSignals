// @ts-check

export const JEFFERSON_INSIGHT_SCHEMA = "shelfsignals-jefferson-insight-graph@1";

const ROOT_FIELDS = [
  "schema", "generated_at", "as_of", "collection_id", "corpus_id", "catalog_source", "config_sha256",
  "methodology", "questions", "sources", "events", "chapter_clusters", "record_relations", "coverage"
];
const EVENT_FIELDS = [
  "id", "kind", "title", "short_title", "date_label", "start_year", "end_year", "phase", "summary",
  "critical_context", "people", "places", "themes", "source_ids", "chapter_groups", "chapter_count",
  "related_record_count", "source_backed_title_count", "direct_relation_count"
];
const GROUP_FIELDS = [
  "chapters", "relationship", "rationale", "context_score", "related_record_count", "source_backed_title_count"
];
const RELATION_FIELDS = [
  "event_id", "record_id", "display_label", "relationship", "claim", "event_use_status",
  "use_confidence_score", "connection_score", "source_ids", "limits"
];
const CHAPTER_FIELDS = [
  "chapter_number", "faculty", "label", "record_count", "source_backed_title_count", "event_ids"
];
const METHODOLOGY_FIELDS = ["context_score", "use_confidence_score", "default_use_assessment", "limitations"];
const COVERAGE_FIELDS = [
  "historical_entries", "historical_chapters", "source_backed_titles", "titles_not_established", "events",
  "chapter_event_edges", "direct_record_relations", "records_with_direct_relations"
];
const USE_STATUSES = new Set([
  "not_established", "documented_interaction", "documented_excerpting", "documented_correspondence_context"
]);
const SAFE_ID = /^[a-z][a-z0-9-]{1,63}$/;
const SHA256 = /^sha256:[a-f0-9]{64}$/;
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function object(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function clean(value) {
  return typeof value === "string" ? value.trim() : "";
}

function exactKeys(value, fields) {
  return object(value)
    && Object.keys(value).sort().join("\u241f") === [...fields].sort().join("\u241f");
}

function stringArray(value) {
  return Array.isArray(value) && value.every(item => clean(item));
}

function boundedScore(value) {
  return Number.isInteger(value) && value >= 0 && value <= 100;
}

function safeLocUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      && (url.hostname === "loc.gov" || url.hostname.endsWith(".loc.gov"));
  } catch (_) {
    return false;
  }
}

function sameObject(left, right) {
  if (!object(left) || !object(right)) return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => left[key] === right[key]);
}

/**
 * Parse and bind an insight graph to the exact historical catalog projection.
 * No partial graph is returned: malformed sources, scores, IDs, or counts
 * disable the feature without weakening the catalog itself.
 */
export function parseJeffersonInsightGraph(raw, { catalogSource = {}, recordIds = new Set(), recordChapters = new Map() } = {}) {
  const reject = reason => ({ rejected: true, errors: [reason], events: [], chapter_clusters: [], record_relations: [] });
  if (!exactKeys(raw, ROOT_FIELDS) || raw.schema !== JEFFERSON_INSIGHT_SCHEMA
    || raw.collection_id !== "jefferson" || raw.corpus_id !== "historical"
    || !UTC.test(clean(raw.generated_at)) || !DATE.test(clean(raw.as_of)) || !SHA256.test(clean(raw.config_sha256))
    || !sameObject(raw.catalog_source, catalogSource)) {
    return reject("Insight graph identity or catalog binding is invalid");
  }
  if (!(recordIds instanceof Set) || !(recordChapters instanceof Map) || recordChapters.size !== recordIds.size
    || [...recordIds].some(id => !Number.isInteger(recordChapters.get(id)) || recordChapters.get(id) < 1 || recordChapters.get(id) > 44)) {
    return reject("Insight graph record-to-chapter binding is invalid");
  }
  if (!exactKeys(raw.methodology, METHODOLOGY_FIELDS)
    || raw.methodology.default_use_assessment !== "not_established"
    || !clean(raw.methodology.context_score) || !clean(raw.methodology.use_confidence_score)
    || !stringArray(raw.methodology.limitations)) {
    return reject("Insight graph methodology is invalid");
  }
  if (!exactKeys(raw.coverage, COVERAGE_FIELDS)
    || raw.coverage.historical_entries !== recordIds.size || raw.coverage.historical_chapters !== 44
    || raw.coverage.source_backed_titles + raw.coverage.titles_not_established !== raw.coverage.historical_entries) {
    return reject("Insight graph coverage does not match the historical corpus");
  }
  if (!Array.isArray(raw.questions) || raw.questions.length !== 4
    || raw.questions.map(question => question?.id).join("\u241f") !== "why-present\u241flife-context\u241fdocumented-use\u241fconnections"
    || raw.questions.some(question => !exactKeys(question, ["id", "label", "prompt"]) || !clean(question.label) || !clean(question.prompt))) {
    return reject("Insight graph questions are invalid");
  }

  if (!Array.isArray(raw.sources) || !raw.sources.length) return reject("Insight graph sources are missing");
  const sourceIds = new Set();
  const sources = [];
  for (const source of raw.sources) {
    if (!exactKeys(source, ["id", "label", "url"]) || !SAFE_ID.test(clean(source.id)) || sourceIds.has(source.id)
      || !clean(source.label) || !safeLocUrl(source.url)) return reject("Insight graph source is invalid");
    sourceIds.add(source.id);
    sources.push({ ...source });
  }

  if (!Array.isArray(raw.events) || raw.events.length !== raw.coverage.events) return reject("Insight graph event count is invalid");
  const eventIds = new Set();
  const events = [];
  let chapterEventEdges = 0;
  for (const event of raw.events) {
    if (!exactKeys(event, EVENT_FIELDS) || !SAFE_ID.test(clean(event.id)) || eventIds.has(event.id)
      || !["event", "life_period"].includes(event.kind) || !clean(event.title) || !clean(event.short_title)
      || !clean(event.date_label) || !clean(event.phase) || !clean(event.summary) || !clean(event.critical_context)
      || !Number.isInteger(event.start_year) || !Number.isInteger(event.end_year)
      || event.start_year < 1743 || event.end_year > 1826 || event.start_year > event.end_year
      || !stringArray(event.people) || !stringArray(event.places) || !stringArray(event.themes)
      || !stringArray(event.source_ids) || event.source_ids.some(id => !sourceIds.has(id))
      || !Array.isArray(event.chapter_groups) || !event.chapter_groups.length
      || !Number.isInteger(event.chapter_count) || !Number.isInteger(event.related_record_count)
      || !Number.isInteger(event.source_backed_title_count) || !Number.isInteger(event.direct_relation_count)) {
      return reject("Insight graph event is invalid");
    }
    eventIds.add(event.id);
    const chapters = new Set();
    for (const group of event.chapter_groups) {
      if (!exactKeys(group, GROUP_FIELDS) || !Array.isArray(group.chapters) || !group.chapters.length
        || group.chapters.some(chapter => !Number.isInteger(chapter) || chapter < 1 || chapter > 44 || chapters.has(chapter))
        || !clean(group.relationship) || !clean(group.rationale) || !boundedScore(group.context_score)
        || !Number.isInteger(group.related_record_count) || !Number.isInteger(group.source_backed_title_count)) {
        return reject("Insight graph chapter group is invalid");
      }
      group.chapters.forEach(chapter => chapters.add(chapter));
      chapterEventEdges += group.chapters.length;
    }
    if (chapters.size !== event.chapter_count) return reject("Insight graph event chapter count is inconsistent");
    events.push({ ...event, chapter_groups: event.chapter_groups.map(group => ({ ...group, chapters: [...group.chapters] })) });
  }
  if (chapterEventEdges !== raw.coverage.chapter_event_edges) return reject("Insight graph chapter-event edge count is inconsistent");

  if (!Array.isArray(raw.chapter_clusters) || raw.chapter_clusters.length !== 44) return reject("Insight graph chapter clusters are incomplete");
  const chapterClusters = [];
  let chapterRecordCount = 0;
  for (let index = 0; index < raw.chapter_clusters.length; index += 1) {
    const chapter = raw.chapter_clusters[index];
    if (!exactKeys(chapter, CHAPTER_FIELDS) || chapter.chapter_number !== index + 1 || !clean(chapter.faculty) || !clean(chapter.label)
      || !Number.isInteger(chapter.record_count) || chapter.record_count <= 0
      || !Number.isInteger(chapter.source_backed_title_count) || chapter.source_backed_title_count < 0
      || chapter.source_backed_title_count > chapter.record_count
      || !Array.isArray(chapter.event_ids) || new Set(chapter.event_ids).size !== chapter.event_ids.length
      || chapter.event_ids.some(id => !eventIds.has(id))) {
      return reject("Insight graph chapter cluster is invalid");
    }
    chapterRecordCount += chapter.record_count;
    chapterClusters.push({ ...chapter, event_ids: [...chapter.event_ids] });
  }
  if (chapterRecordCount !== recordIds.size) return reject("Insight graph chapter clusters do not reconcile to the catalog");
  const chapterByNumber = new Map(chapterClusters.map(chapter => [chapter.chapter_number, chapter]));
  if (chapterClusters.reduce((sum, chapter) => sum + chapter.source_backed_title_count, 0) !== raw.coverage.source_backed_titles) {
    return reject("Insight graph title coverage does not reconcile to its chapter clusters");
  }
  const eventChapterIds = new Map();
  for (const event of events) {
    const chapters = new Set(event.chapter_groups.flatMap(group => group.chapters));
    eventChapterIds.set(event.id, chapters);
    let relatedRecords = 0;
    let sourceBackedTitles = 0;
    for (const group of event.chapter_groups) {
      const groupRecords = group.chapters.reduce((sum, chapter) => sum + chapterByNumber.get(chapter).record_count, 0);
      const groupTitles = group.chapters.reduce((sum, chapter) => sum + chapterByNumber.get(chapter).source_backed_title_count, 0);
      if (group.related_record_count !== groupRecords || group.source_backed_title_count !== groupTitles) {
        return reject("Insight graph event group coverage is inconsistent");
      }
      relatedRecords += groupRecords;
      sourceBackedTitles += groupTitles;
    }
    if (event.related_record_count !== relatedRecords || event.source_backed_title_count !== sourceBackedTitles) {
      return reject("Insight graph event coverage is inconsistent");
    }
  }
  for (const chapter of chapterClusters) {
    const expected = events.filter(event => eventChapterIds.get(event.id).has(chapter.chapter_number)).map(event => event.id).sort();
    if ([...chapter.event_ids].sort().join("\u241f") !== expected.join("\u241f")) {
      return reject("Insight graph chapter-event membership is inconsistent");
    }
  }

  if (!Array.isArray(raw.record_relations) || raw.record_relations.length !== raw.coverage.direct_record_relations) {
    return reject("Insight graph record relation count is invalid");
  }
  const relationKeys = new Set();
  const relations = [];
  const relatedRecordIds = new Set();
  const directCounts = new Map();
  for (const relation of raw.record_relations) {
    const key = `${relation?.event_id}\u241f${relation?.record_id}`;
    if (!exactKeys(relation, RELATION_FIELDS) || !eventIds.has(relation.event_id) || !recordIds.has(relation.record_id)
      || !eventChapterIds.get(relation.event_id)?.has(recordChapters.get(relation.record_id))
      || relationKeys.has(key) || !clean(relation.display_label) || !clean(relation.relationship) || !clean(relation.claim)
      || !USE_STATUSES.has(relation.event_use_status) || !boundedScore(relation.connection_score)
      || (relation.event_use_status === "not_established" ? relation.use_confidence_score !== null : !boundedScore(relation.use_confidence_score))
      || !stringArray(relation.source_ids) || relation.source_ids.some(id => !sourceIds.has(id)) || !clean(relation.limits)) {
      return reject("Insight graph record relation is invalid");
    }
    relationKeys.add(key);
    relatedRecordIds.add(relation.record_id);
    directCounts.set(relation.event_id, (directCounts.get(relation.event_id) || 0) + 1);
    relations.push({ ...relation, source_ids: [...relation.source_ids] });
  }
  if (relatedRecordIds.size !== raw.coverage.records_with_direct_relations
    || events.some(event => event.direct_relation_count !== (directCounts.get(event.id) || 0))) {
    return reject("Insight graph direct relation coverage is inconsistent");
  }

  const eventById = new Map(events.map(event => [event.id, event]));
  const sourceById = new Map(sources.map(source => [source.id, source]));
  const relationsByRecord = new Map();
  relations.forEach(relation => {
    if (!relationsByRecord.has(relation.record_id)) relationsByRecord.set(relation.record_id, []);
    relationsByRecord.get(relation.record_id).push(relation);
  });
  return {
    ...raw,
    rejected: false,
    sources,
    events,
    chapter_clusters: chapterClusters,
    record_relations: relations,
    eventById,
    sourceById,
    chapterByNumber,
    relationsByRecord
  };
}

export function eventContextForRecord(graph, record) {
  if (!graph || graph.rejected || !record || !Number.isInteger(record.chapter_number)) return [];
  return graph.events.flatMap(event => event.chapter_groups
    .filter(group => group.chapters.includes(record.chapter_number))
    .map(group => ({ event, group, direct: (graph.relationsByRecord.get(record.id) || []).find(relation => relation.event_id === event.id) || null })));
}
