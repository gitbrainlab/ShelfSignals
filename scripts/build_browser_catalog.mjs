#!/usr/bin/env node

/**
 * Build deterministic browser projections from the canonical Clark catalog.
 *
 * The full `sekula_index.json` remains authoritative. These compact files
 * reduce first-load parsing while retaining a lazy, source-identical search
 * and detail path for every one of its records.
 */

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { enrichRecord } from "../docs/js/catalog.js";
import {
  BROWSER_CATALOG_SCHEMA,
  CATALOG_DETAIL_INDEX_SCHEMA,
  CATALOG_DETAIL_SCHEMA,
  CATALOG_SEARCH_SCHEMA,
  CORE_FIELDS,
  DETAIL_FIELDS,
  HOLDING_FIELDS,
  PLACEMENT_FIELDS,
  SEARCH_FIELDS,
  detailShardName,
  stableCatalogShard
} from "../docs/js/catalog-data.js";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = path.resolve(SCRIPT_DIR, "..");
const DEFAULT_CATALOG = path.join(REPOSITORY_ROOT, "docs/data/sekula_index.json");
const DEFAULT_CORE = path.join(REPOSITORY_ROOT, "docs/data/catalog-core.json");
const DEFAULT_SEARCH = path.join(REPOSITORY_ROOT, "docs/data/catalog-search.json");
const DEFAULT_DETAILS = path.join(REPOSITORY_ROOT, "docs/data/catalog-details");
const DEFAULT_SHARD_COUNT = 128;
const RECORD_URL_TEMPLATE = "https://library.clarkart.edu/discovery/fulldisplay?docid={id}&context=L&vid=01CLARKART_INST%3A01CLARKART_INST_FRANCINE&lang=en&tab=LibraryCatalog";
const UTC_DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;

function sha256(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function jsonBytes(value) {
  return Buffer.from(`${JSON.stringify(value)}\n`, "utf8");
}

function stringArray(value) {
  return Array.isArray(value) ? value.filter(entry => entry != null && entry !== "").map(String) : [];
}

function stringValue(value) {
  return value == null ? "" : String(value);
}

function compactHolding(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const row = [
    stringValue(value.subLocation),
    stringValue(value.subLocationCode),
    stringValue(value.callNumber),
    stringValue(value.availabilityStatus)
  ];
  return row.some(Boolean) ? row : null;
}

function detailValue(record, field) {
  if (field === "id") return stringValue(record.id);
  if (field === "best_location") return compactHolding(record.best_location);
  if (field === "holdings") return (Array.isArray(record.holdings) ? record.holdings : []).map(compactHolding).filter(Boolean);
  if ([
    "alternative_titles", "contributors", "languages", "identifiers", "publishers", "places", "series",
    "table_of_contents", "notes", "provenance_notes", "sekula_notes", "subjects", "collection_tags",
    "call_number_notes", "isbns", "issns", "oclc_numbers", "lccn"
  ].includes(field)) return stringArray(record[field]);
  return stringValue(record[field]);
}

export function projectDetailRecord(record) {
  return DETAIL_FIELDS.map(field => detailValue(record, field));
}

function generatedAtFromEnvironment() {
  const epoch = Number(process.env.SOURCE_DATE_EPOCH);
  if (Number.isFinite(epoch) && epoch >= 0) return new Date(epoch * 1000).toISOString().replace(".000Z", "Z");
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function validateCanonicalRecords(records) {
  assert.ok(Array.isArray(records) && records.length, "Canonical catalog must be a non-empty array");
  const ids = new Set();
  for (const [index, record] of records.entries()) {
    assert.ok(record && typeof record === "object" && !Array.isArray(record), `Record ${index} must be an object`);
    const id = stringValue(record.id).trim();
    assert.ok(id && /^[A-Za-z0-9._~-]+$/.test(id), `Record ${index} has an unsafe ID`);
    assert.ok(!ids.has(id), `Duplicate catalog ID: ${id}`);
    assert.ok(stringValue(record.title).trim(), `Record ${id} has no canonical title`);
    const expectedUrl = RECORD_URL_TEMPLATE.replace("{id}", encodeURIComponent(id));
    assert.equal(record.record_url, expectedUrl, `Record ${id} has a non-canonical Clark URL`);
    ids.add(id);
  }
  return ids;
}

/**
 * Build all projection payloads in memory. Exported for deterministic tests.
 */
export function buildBrowserCatalog({ records, catalogBytes, generatedAt, shardCount = DEFAULT_SHARD_COUNT }) {
  const catalogIds = validateCanonicalRecords(records);
  assert.ok(Buffer.isBuffer(catalogBytes) || catalogBytes instanceof Uint8Array, "Raw canonical bytes are required for identity binding");
  assert.ok(UTC_DATE.test(generatedAt), "generatedAt must be a whole-second UTC timestamp");
  assert.ok(Number.isInteger(shardCount) && shardCount >= 1 && shardCount <= 1000, "shardCount must be an integer from 1 to 1000");

  const orderedIds = records.map(record => String(record.id));
  const source = {
    catalog: "Clark Library Catalog",
    dataset: "sekula_index.json",
    dataset_sha256: sha256(catalogBytes),
    record_count: records.length,
    id_set_sha256: sha256(Buffer.from(`${orderedIds.join("\n")}\n`, "utf8")),
    record_url_template: RECORD_URL_TEMPLATE
  };
  const shardSource = {
    catalog: source.catalog,
    dataset: source.dataset,
    dataset_sha256: source.dataset_sha256,
    record_count: source.record_count,
    id_set_sha256: source.id_set_sha256
  };

  const coreItems = [];
  const searchItems = [];
  const detailItems = Array.from({ length: shardCount }, () => []);

  for (const record of records) {
    const enriched = enrichRecord(record);
    const shard = stableCatalogShard(enriched.id, shardCount);
    const placements = enriched.placements.map(placement => [
      stringValue(placement.label),
      stringValue(placement.key),
      stringValue(placement.roomLabel),
      stringValue(placement.roomKey)
    ]);
    coreItems.push([
      enriched.id,
      enriched.title,
      enriched.authors,
      stringValue(enriched.year),
      stringValue(enriched.call_number),
      stringValue(enriched.material_type),
      enriched.formats,
      stringValue(enriched.photo_insert_bucket),
      Number.isFinite(Number(enriched.photo_insert_score)) ? Number(enriched.photo_insert_score) : null,
      placements,
      enriched.signals,
      shard
    ]);
    searchItems.push([enriched.id, enriched.searchText]);
    detailItems[shard].push(projectDetailRecord(record));
  }

  assert.equal(catalogIds.size, coreItems.length, "Every canonical record must appear once in the core projection");
  const core = {
    schema: BROWSER_CATALOG_SCHEMA,
    generated_at: generatedAt,
    source,
    contract: {
      core_fields: [...CORE_FIELDS],
      placement_fields: [...PLACEMENT_FIELDS],
      detail_shard_count: shardCount,
      detail_path_template: "catalog-details/{shard}.json",
      search_path: "catalog-search.json"
    },
    items: coreItems
  };
  const search = {
    schema: CATALOG_SEARCH_SCHEMA,
    generated_at: generatedAt,
    source: shardSource,
    fields: [...SEARCH_FIELDS],
    items: searchItems
  };
  const detailShards = detailItems.map((items, shard) => ({
    schema: CATALOG_DETAIL_SCHEMA,
    generated_at: generatedAt,
    source: shardSource,
    shard,
    shard_count: shardCount,
    item_count: items.length,
    fields: [...DETAIL_FIELDS],
    holding_fields: [...HOLDING_FIELDS],
    items
  }));

  const detailIndex = {
    schema: CATALOG_DETAIL_INDEX_SCHEMA,
    generated_at: generatedAt,
    source: shardSource,
    shard_count: shardCount,
    fields: [...DETAIL_FIELDS],
    holding_fields: [...HOLDING_FIELDS],
    shards: detailShards.map((payload, shard) => {
      const bytes = jsonBytes(payload);
      return {
        shard,
        file: detailShardName(shard),
        item_count: payload.item_count,
        bytes: bytes.byteLength,
        sha256: sha256(bytes)
      };
    })
  };

  return { core, search, detailIndex, detailShards };
}

function outputFiles(build, { coreOutput, searchOutput, detailsDir }) {
  const files = new Map([
    [coreOutput, jsonBytes(build.core)],
    [searchOutput, jsonBytes(build.search)],
    [path.join(detailsDir, "index.json"), jsonBytes(build.detailIndex)]
  ]);
  build.detailShards.forEach((payload, shard) => files.set(path.join(detailsDir, detailShardName(shard)), jsonBytes(payload)));
  return files;
}

async function writeBuild(files, detailsDir) {
  await mkdir(path.dirname([...files.keys()][0]), { recursive: true });
  await mkdir(detailsDir, { recursive: true });
  const expectedDetailNames = new Set([...files.keys()].filter(file => path.dirname(file) === detailsDir).map(file => path.basename(file)));
  for (const name of await readdir(detailsDir)) {
    if (/^\d{3}\.json$/.test(name) && !expectedDetailNames.has(name)) await unlink(path.join(detailsDir, name));
  }
  for (const [file, bytes] of files) {
    await mkdir(path.dirname(file), { recursive: true });
    await writeFile(file, bytes);
  }
}

async function checkBuild(files, detailsDir) {
  const failures = [];
  for (const [file, expected] of files) {
    if (!existsSync(file)) {
      failures.push(`${path.relative(REPOSITORY_ROOT, file)} is missing`);
      continue;
    }
    const actual = await readFile(file);
    if (!actual.equals(expected)) failures.push(`${path.relative(REPOSITORY_ROOT, file)} is stale`);
  }
  if (existsSync(detailsDir)) {
    const expectedNames = new Set([...files.keys()].filter(file => path.dirname(file) === detailsDir).map(file => path.basename(file)));
    for (const name of await readdir(detailsDir)) {
      if (/^\d{3}\.json$/.test(name) && !expectedNames.has(name)) failures.push(`${path.relative(REPOSITORY_ROOT, path.join(detailsDir, name))} is stale`);
    }
  }
  if (failures.length) throw new Error(`Browser catalog check failed:\n- ${failures.join("\n- ")}`);
}

export function parseArgs(argv) {
  const options = {
    catalog: DEFAULT_CATALOG,
    coreOutput: DEFAULT_CORE,
    searchOutput: DEFAULT_SEARCH,
    detailsDir: DEFAULT_DETAILS,
    shardCount: DEFAULT_SHARD_COUNT,
    generatedAt: "",
    check: false,
    selfTest: false
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    const value = () => {
      const next = argv[index + 1];
      if (!next || next.startsWith("--")) throw new Error(`${argument} requires a value`);
      index += 1;
      return next;
    };
    if (argument === "--catalog") options.catalog = path.resolve(value());
    else if (argument === "--core-output") options.coreOutput = path.resolve(value());
    else if (argument === "--search-output") options.searchOutput = path.resolve(value());
    else if (argument === "--details-dir") options.detailsDir = path.resolve(value());
    else if (argument === "--shard-count") options.shardCount = Number(value());
    else if (argument === "--generated-at") options.generatedAt = value();
    else if (argument === "--check") options.check = true;
    else if (argument === "--self-test") options.selfTest = true;
    else if (argument === "--help") options.help = true;
    else throw new Error(`Unknown argument: ${argument}`);
  }
  return options;
}

function help() {
  return `Usage: node scripts/build_browser_catalog.mjs [options]\n\n` +
    `  --catalog PATH       Canonical sekula_index.json\n` +
    `  --core-output PATH   Compact first-load output\n` +
    `  --search-output PATH Lazy full-field search output\n` +
    `  --details-dir PATH   Lazy detail-shard directory\n` +
    `  --shard-count N      Deterministic shard count (default 128)\n` +
    `  --generated-at UTC   Whole-second ISO UTC timestamp\n` +
    `  --check              Fail when committed projections are stale\n` +
    `  --self-test          Run an in-memory deterministic self-test\n`;
}

export function runSelfTest() {
  const records = ["alma1", "alma2"].map((id, index) => ({
    id,
    title: `Test title ${index + 1}`,
    authors: [`Creator ${index + 1}`],
    year: `200${index}`,
    call_number: `NE2698 .S4637L 0000${index + 1}`,
    material_type: "book",
    formats: ["100 pages : illustrations ; 24 cm"],
    subjects: [index ? "Shipping" : "Photography"],
    provenance_notes: [`Gift; Sekula Library Identifier: Front Bedroom ${index ? "B" : "A"}`],
    isbns: [],
    holdings: [],
    record_url: RECORD_URL_TEMPLATE.replace("{id}", id)
  }));
  const catalogBytes = Buffer.from(JSON.stringify(records));
  const first = buildBrowserCatalog({ records, catalogBytes, generatedAt: "2026-07-14T00:00:00Z", shardCount: 4 });
  const second = buildBrowserCatalog({ records, catalogBytes, generatedAt: "2026-07-14T00:00:00Z", shardCount: 4 });
  assert.deepEqual(first, second);
  assert.equal(first.core.items.length, 2);
  assert.equal(first.search.items.length, 2);
  assert.equal(first.detailShards.reduce((sum, shard) => sum + shard.item_count, 0), 2);
  assert.equal(first.core.items[0][9][0][0], "Front Bedroom A");
  assert.ok(first.search.items[1][1].includes("shipping"));
  return true;
}

export async function main(argv = process.argv.slice(2)) {
  const options = parseArgs(argv);
  if (options.help) {
    process.stdout.write(help());
    return;
  }
  if (options.selfTest) {
    runSelfTest();
    process.stdout.write("Browser catalog self-test passed.\n");
    return;
  }
  const catalogBytes = await readFile(options.catalog);
  const records = JSON.parse(catalogBytes.toString("utf8"));
  let generatedAt = options.generatedAt || generatedAtFromEnvironment();
  if (options.check && !options.generatedAt && existsSync(options.coreOutput)) {
    const existing = JSON.parse(await readFile(options.coreOutput, "utf8"));
    if (UTC_DATE.test(existing.generated_at || "")) generatedAt = existing.generated_at;
  }
  const build = buildBrowserCatalog({ records, catalogBytes, generatedAt, shardCount: options.shardCount });
  const files = outputFiles(build, options);
  if (options.check) await checkBuild(files, options.detailsDir);
  else await writeBuild(files, options.detailsDir);
  const coreBytes = files.get(options.coreOutput).byteLength;
  const searchBytes = files.get(options.searchOutput).byteLength;
  const detailBytes = [...files.entries()].filter(([file]) => path.dirname(file) === options.detailsDir).reduce((sum, [, bytes]) => sum + bytes.byteLength, 0);
  process.stdout.write(`${options.check ? "Verified" : "Built"} ${records.length.toLocaleString()} records · core ${coreBytes.toLocaleString()} B · search ${searchBytes.toLocaleString()} B · details ${detailBytes.toLocaleString()} B\n`);
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  main().catch(error => {
    console.error(error.stack || error.message || error);
    process.exitCode = 1;
  });
}
