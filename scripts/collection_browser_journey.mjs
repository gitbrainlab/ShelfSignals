#!/usr/bin/env node

import fs from "node:fs";

const runtimeProcess = typeof process === "undefined" ? { argv: [], env: {} } : process;
const baseUrl = new URL(runtimeProcess.argv?.[2] || "http://127.0.0.1:8000/");
const playwrightModule = runtimeProcess.env.SHELFSIGNALS_PLAYWRIGHT_MODULE || "playwright";
const chromeExecutable = runtimeProcess.env.SHELFSIGNALS_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function report(message) {
  console.log(`[PASS] ${message}`);
}

async function ready(page) {
  await page.waitForSelector('body[data-app-state="ready"]', { timeout: 60_000 });
}

async function text(page, selector) {
  return (await page.locator(selector).innerText()).trim();
}

async function assertHeroClearsBanners(page, label) {
  await page.waitForFunction(() => {
    const banners = document.querySelector("#modeBanners");
    const reserved = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--mode-banners-h")) || 0;
    return banners && Math.abs(reserved - banners.getBoundingClientRect().height) <= 1;
  });
  const geometry = await page.evaluate(() => {
    const banners = document.querySelector("#modeBanners").getBoundingClientRect();
    const heroCopy = document.querySelector(".hero-copy").getBoundingClientRect();
    return { bannerBottom: banners.bottom, heroCopyTop: heroCopy.top };
  });
  check(geometry.heroCopyTop + 1 >= geometry.bannerBottom, `${label} banners overlap the hero copy`);
}

const { chromium } = await import(playwrightModule);
const launchOptions = { headless: true };
if (fs.existsSync(chromeExecutable)) launchOptions.executablePath = chromeExecutable;
else launchOptions.channel = "chrome";

const browser = await chromium.launch(launchOptions);
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  const requests = [];
  const pageErrors = [];
  page.on("request", request => requests.push(request.url()));
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.route(/^https:\/\/(www\.)?loc\.gov\//, route => route.abort("blockedbyclient"));
  await page.route(/^https:\/\/tile\.loc\.gov\//, route => route.abort("blockedbyclient"));

  await page.goto(baseUrl.href, { waitUntil: "domcontentloaded" });
  await ready(page);
  check((await page.title()).includes("Allan Sekula Library"), "default title is Sekula");
  check(await page.locator("#collectionSwitcher").inputValue() === "sekula", "default switcher is Sekula");
  check(!new URL(page.url()).searchParams.has("collection"), "default URL stays canonical");
  check(await text(page, "#collectionCount") === "11,176", "Sekula record count changed");
  check(!(await page.locator("#collectionStatusBanner").isVisible()), "Jefferson beta banner leaked into Sekula");
  check(await page.locator("#journeys").isVisible(), "Sekula journey was disabled");
  check(await page.locator('.view-button[data-view="spines"]').isVisible(), "Sekula physical view was disabled");
  report("default Sekula route remains backward compatible");

  await page.locator(".book-card .book-open").first().click();
  await page.locator("#detailLoading").waitFor({ state: "hidden" });
  await page.locator("#detailShelfButton").click();
  await page.locator("#closeDetail").click();
  const sekulaShelf = await page.evaluate(() => localStorage.getItem("shelfsignals_shelf"));
  check(JSON.parse(sekulaShelf || "[]").length === 1, "Sekula shelf did not persist under its legacy key");

  const jeffersonRequestStart = requests.length;
  await page.locator("#collectionSwitcher").selectOption("jefferson");
  await page.waitForURL(url => url.searchParams.get("collection") === "jefferson");
  await ready(page);
  const jeffersonUrl = new URL(page.url());
  check(jeffersonUrl.searchParams.get("corpus") === "catalog", "Jefferson Phase 1 corpus was not canonicalized to catalog");
  check(jeffersonUrl.searchParams.get("order") === "title", "Jefferson Phase 1 order was not canonicalized to title");
  check((await page.title()).includes("Thomas Jefferson's Library"), "Jefferson title did not load");
  check(await page.locator("#corpusSwitcher").isVisible(), "Jefferson corpus selector is hidden");
  check(await page.locator("#corpusSwitcher").inputValue() === "catalog", "Phase 1 corpus selector is not on catalog");
  check(!(await page.locator("#corpusSwitcher").isDisabled()), "dual-corpus Jefferson selector is unexpectedly read-only");
  check(await text(page, "#collectionCount") === "2,748", "Jefferson catalog-instance count is wrong");
  const coverageWarning = await text(page, "#collectionStatusText");
  check(coverageWarning.includes("4,928 source-backed Sowerby entries") && coverageWarning.includes("4,931 historical source positions"), "beta coverage warning is incomplete or conflates positions with entries");
  check(await text(page, "#jeffersonHistoricalCount") === "4,928", "source-backed Sowerby entry count is wrong");
  check(await text(page, "#jeffersonPositionCount") === "4,931", "historical catalog-position count is wrong");
  check((await text(page, "#jeffersonEvidenceSummary")).includes("2323, 4707, 4708"), "source-numbering gaps are not visible");
  check(await page.locator("#collectionStatusBanner").isVisible(), "beta coverage warning is not unavoidable");
  check(await page.locator("#jeffersonOverview").isVisible(), "Jefferson evidence overview is hidden");
  check(await page.locator("#jeffersonHierarchyContent details").count() === 3, "faculty hierarchy is incomplete");
  check(await page.locator("#jeffersonHierarchyContent li").count() === 44, "44 Sowerby chapters are not rendered");
  check(!(await page.locator("#journeys").isVisible()), "Sekula journeys leaked into Jefferson");
  check(!(await page.locator("#paths").isVisible()), "Sekula paths leaked into Jefferson");
  check(!(await page.locator("#signals").isVisible()), "Sekula signals leaked into Jefferson");
  check(!(await page.locator('.view-button[data-view="spines"]').isVisible()), "physical reconstruction leaked into Jefferson");
  check(!(await page.locator("#groupFilter").locator("xpath=ancestor::fieldset").isVisible()), "physical grouping leaked into Jefferson");
  const jeffersonRequests = requests.slice(jeffersonRequestStart);
  check(!jeffersonRequests.some(url => url.includes("media-review.json")), "review media loaded before unlock");
  check(!jeffersonRequests.some(url => url.includes("covers.openlibrary.org")), "Sekula cover provider leaked into Jefferson");
  check(!jeffersonRequests.some(url => url.includes("catalog-search.json")), "Jefferson search projection loaded before search");
  check(!jeffersonRequests.some(url => /(?:\.jsonl|\.sqlite(?:$|[?#])|\/research\/jefferson\/)/i.test(url)), "raw Jefferson research data was requested by the browser");
  check(await page.evaluate(() => localStorage.getItem("shelfsignals_shelf:jefferson")) === null, "Jefferson inherited the Sekula shelf");
  await assertHeroClearsBanners(page, "desktop public-mode");
  report("Jefferson beta loads with isolated features, assets, hierarchy, and shelf state");

  const craftedStateUrl = new URL(page.url());
  for (const [key, value] of Object.entries({ signals: "labor", signalMode: "all", photo: "high", placement: "east", group: "material", path: "one", journey: "two", cluster: "three", view: "spines" })) {
    craftedStateUrl.searchParams.set(key, value);
  }
  await page.goto(craftedStateUrl.href, { waitUntil: "domcontentloaded" });
  await ready(page);
  const normalizedJeffersonState = new URL(page.url());
  for (const key of ["signals", "signalMode", "photo", "placement", "group", "path", "journey", "cluster", "view"]) {
    check(!normalizedJeffersonState.searchParams.has(key), `${key} leaked into canonical Jefferson state`);
  }

  await page.locator("#orderFilter").selectOption("lc");
  await page.waitForFunction(() => new URL(location.href).searchParams.get("order") === "lc");
  await page.reload({ waitUntil: "domcontentloaded" });
  await ready(page);
  check(await page.locator("#orderFilter").inputValue() === "lc", "Jefferson order did not survive reload");
  await page.locator("#evidenceFilter").selectOption("sowerby_510_exact_bounded");
  await page.waitForFunction(() => document.querySelector("#resultSummary")?.textContent?.startsWith("17 of 2,748"));
  check(new URL(page.url()).searchParams.get("evidence") === "sowerby_510_exact_bounded", "evidence filter did not enter URL state");
  report("Jefferson ordering and bounded-evidence filtering are URL-stable");

  await page.locator(".book-card .book-open").first().click();
  await page.locator("#detailLoading").waitFor({ state: "hidden" });
  const detailCopy = await text(page, "#detailMetadata");
  const detailCopyLower = detailCopy.toLocaleLowerCase();
  check(detailCopy.includes("CATALOG INSTANCE ID"), "drawer does not identify the catalog-instance entity");
  check(detailCopyLower.includes("ownership not established"), "drawer conflates heading membership with ownership");
  check(detailCopyLower.includes("reconstruction status\nnot established"), "drawer does not label unresolved reconstruction status");
  check(await page.locator("#detailPlacement").isHidden(), "Sekula placement appears in Jefferson drawer");
  check(await page.locator("#detailPhysical").isHidden(), "physical reconstruction appears in Jefferson drawer");
  await page.locator("#detailShelfButton").click();
  await page.locator("#closeDetail").click();
  const jeffersonShelf = await page.evaluate(() => localStorage.getItem("shelfsignals_shelf:jefferson"));
  check(JSON.parse(jeffersonShelf || "[]").length === 1, "Jefferson shelf did not persist separately");

  await page.locator("#openShelf").click();
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#exportReceipt").click();
  const download = await downloadPromise;
  const receiptPath = await download.path();
  check(download.suggestedFilename() === "jefferson-shelf.json", "Jefferson receipt filename ignores its manifest");
  await page.locator("#closeShelf").click();

  await page.evaluate(() => history.replaceState(history.state, "", `${location.pathname}${location.search}#jeffersonOverview`));
  await page.locator("#collectionSwitcher").selectOption("sekula");
  await page.waitForURL(url => !url.searchParams.has("collection"));
  await ready(page);
  check(new URL(page.url()).hash === "", "collection-specific hash leaked across a collection switch");
  await page.locator('input[type="file"][accept*="json"]').setInputFiles(receiptPath);
  await page.waitForFunction(() => document.querySelector("#toast")?.textContent?.includes("another collection"));
  check((await text(page, "#toast")).includes("another collection"), "wrong-collection receipt was not rejected");
  check(JSON.parse(await page.evaluate(() => localStorage.getItem("shelfsignals_shelf")) || "[]").length === 1, "wrong receipt replaced the Sekula shelf");
  await page.goBack({ waitUntil: "domcontentloaded" });
  await ready(page);
  check(new URL(page.url()).searchParams.get("collection") === "jefferson", "Back did not restore the Jefferson collection");
  report("separate receipts and collection Back navigation are enforced");

  const beforeWrongCode = requests.filter(url => url.includes("media-review.json")).length;
  await page.locator("#openReviewerMode").click();
  await page.locator("#reviewerCode").fill("wrong-code");
  await page.locator("#unlockReviewerMode").click();
  check(await page.locator("#reviewerCodeError").isVisible(), "invalid reviewer code did not fail visibly");
  check(requests.filter(url => url.includes("media-review.json")).length === beforeWrongCode, "invalid code requested review media");
  await page.locator("#reviewerCode").fill("TJ1815");
  const reviewResponse = page.waitForResponse(response => response.url().includes("media-review.json") && response.status() === 200);
  await page.locator("#unlockReviewerMode").click();
  await reviewResponse;
  check(await page.locator("#reviewerModeBanner").isVisible(), "review warning is not persistent after unlock");
  check((await text(page, "#reviewerModeStatus")).toLocaleLowerCase().includes("not access controlled"), "review warning overstates security");
  for (const viewport of [{ width: 1440, height: 1000, label: "desktop reviewer-mode" }, { width: 820, height: 900, label: "tablet reviewer-mode" }, { width: 390, height: 844, label: "mobile reviewer-mode" }]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.evaluate(() => scrollTo(0, 0));
    await assertHeroClearsBanners(page, viewport.label);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });

  const exactId = "jefferson-loc-89f398bf-0d30-50a0-8129-3ecccdc869de";
  const exactUrl = new URL(baseUrl.href);
  exactUrl.searchParams.set("collection", "jefferson");
  exactUrl.searchParams.set("record", exactId);
  await page.goto(exactUrl.href, { waitUntil: "domcontentloaded" });
  await ready(page);
  await page.locator("#detailDrawer.open").waitFor();
  await page.locator("#detailLoading").waitFor({ state: "hidden" });
  const mediaEvidence = await text(page, "#detailCoverEvidenceBody");
  const currentLocEvidence = await text(page, "#detailMetadata");
  check(mediaEvidence.includes("Review media—not cleared for reuse"), "review media is presented as cleared");
  check(mediaEvidence.includes("RIGHTS & ACCESS"), "item-level Rights & Access evidence is missing");
  check(await page.locator("#detailCoverEvidenceBody img").count() === 1, "unlocked LOC preview was not rendered");
  check(currentLocEvidence.includes("CURRENT LOC ITEM STATUS\nAvailable"), "current LOC item status is not surfaced");
  check(currentLocEvidence.includes("CURRENT LOC ITEM LOCATION\nRare Book and Special Collection Reading Room"), "current LOC item location is not surfaced");
  check(currentLocEvidence.includes("CURRENT LOC HOLDING LOCATION\nRare Book and Special Collection Reading Room"), "current LOC holding location is not surfaced");
  await page.locator("#closeDetail").click();
  await page.locator("#exitReviewerMode").click();
  check(!(await page.locator("#reviewerModeBanner").isVisible()), "review mode did not exit");
  report("review media stays lazy, tab-local, warned, and evidence-scoped");

  const historicalRequestStart = requests.length;
  await page.locator("#corpusSwitcher").selectOption("historical");
  await page.waitForURL(url => url.searchParams.get("corpus") === "historical" && url.searchParams.get("order") === "sowerby");
  await ready(page);
  check(await page.locator("#corpusSwitcher").inputValue() === "historical", "historical corpus selection did not survive reload");
  check(await page.locator("#orderFilter").inputValue() === "sowerby", "historical corpus did not default to Sowerby order");
  check(await text(page, "#collectionCount") === "4,928", "historical source-backed entry count is wrong");
  check((await text(page, "#collectionStatusText")).includes("4,928 source-backed entries"), "historical beta coverage warning is incomplete");
  check((await text(page, "#jeffersonEvidenceSummary")).includes("2323, 4707, 4708"), "historical source-number gaps are not visible");
  check((await text(page, "#jeffersonEvidenceSummary")).includes("short titles passed")
    && (await text(page, "#jeffersonEvidenceSummary")).includes("remain explicitly not established"), "historical title coverage is not explicit");
  check((await text(page, "#jeffersonEvidenceSummary")).includes("exact LOC PDF page")
    && (await text(page, "#jeffersonEvidenceSummary")).includes("aggregate scan-spine support"), "historical identifier evidence levels are collapsed");
  const historicalOverviewKicker = await text(page, ".collection-overview-header .section-index");
  const historicalCollectionKicker = (await page.locator(".collection-header .section-index").textContent() || "").trim();
  check(historicalOverviewKicker.toLocaleLowerCase() === "jefferson historical beta", `historical overview is mislabeled as a catalog beta: ${historicalOverviewKicker}`);
  check(historicalCollectionKicker.toLocaleLowerCase() === "04 / historical corpus beta", `historical browser is mislabeled as complete: ${historicalCollectionKicker}`);
  const historicalClassCount = await text(page, "#classCount");
  const historicalClassUnit = (await page.locator("#classCount + dd").textContent() || "").trim();
  const historicalYearSpan = await text(page, "#yearSpan");
  const historicalYearUnit = (await page.locator("#yearSpan + dd").textContent() || "").trim();
  check(historicalClassCount === "44" && historicalClassUnit.toLocaleLowerCase() === "historical chapters", `historical stats imply LC classes: ${historicalClassCount} / ${historicalClassUnit}`);
  check(historicalYearSpan === "Not established" && historicalYearUnit.toLocaleLowerCase() === "publication dates", `historical stats imply cataloged dates: ${historicalYearSpan} / ${historicalYearUnit}`);
  const historicalCardMeta = (await page.locator(".book-card .book-card-meta").first().textContent() || "").trim();
  const historicalCardEvidence = (await page.locator(".book-card .book-card-cover-scope").first().textContent() || "").trim();
  check(historicalCardMeta.toLocaleLowerCase().includes("creator not established") && historicalCardMeta.toLocaleLowerCase().includes("date not established"), `historical cards imply absent creator/date facts: ${historicalCardMeta}`);
  check(historicalCardEvidence.toLocaleLowerCase().includes("no digital object relation established"), `historical cards imply unavailable digital-object evidence exists: ${historicalCardEvidence}`);
  check(await page.locator("#lcFilter").locator("xpath=ancestor::fieldset").isHidden(), "undeclared LC facet is visible in the historical corpus");
  check(await page.locator("#materialFilter").locator("xpath=ancestor::fieldset").isHidden(), "undeclared material facet is visible in the historical corpus");
  check(await page.locator("#decadeFilter").locator("xpath=ancestor::fieldset").isHidden(), "undeclared decade facet is visible in the historical corpus");
  check(await page.locator("#openReviewerMode").isHidden(), "catalog-only public reviewer media leaked into the historical corpus");
  check(!(await page.locator('.view-button[data-view="spines"]').isVisible()), "physical reconstruction leaked into the historical corpus");
  check(await page.locator("#jeffersonInsights").isVisible(), "historical life-event evidence graph is hidden");
  check(await page.locator("#jeffersonInsightsNav").isVisible(), "life-event navigation is hidden");
  check(await page.locator("#insightQuestions article").count() === 4, "question-driven evidence graph is incomplete");
  check(await page.locator("#lifeEventTimeline .life-event-node").count() === 9, "life-event timeline is incomplete");
  const historicalRequests = requests.slice(historicalRequestStart);
  check(historicalRequests.some(url => url.includes("/historical/catalog-core.json")), "historical core was not requested from its namespace");
  check(historicalRequests.some(url => url.includes("/historical/validation.json")), "historical validation was not requested from its namespace");
  check(historicalRequests.some(url => url.includes("/historical/insights.json")), "historical insight graph was not requested from its namespace");
  check(!historicalRequests.some(url => /(?:\.jsonl|\.sqlite(?:$|[?#])|\/research\/jefferson\/)/i.test(url)), "raw research data was requested by the historical browser");

  const adamsEvent = page.locator("#lifeEventTimeline .life-event-node").filter({ hasText: "Adams's package" });
  await adamsEvent.click();
  await page.waitForFunction(() => new URL(location.href).searchParams.get("event") === "adams-homespun-1812");
  await page.waitForFunction(() => document.querySelector("#resultSummary")?.textContent?.startsWith("50 of 4,928"));
  const adamsEventPanel = await text(page, "#lifeEventPanel");
  check(adamsEventPanel.includes("Lectures on Rhetoric and Oratory"), "documented Adams volume is absent from its event");
  check(adamsEventPanel.toLocaleLowerCase().includes("evidence confidence 98/100"), `documented interaction confidence is not visible: ${JSON.stringify(adamsEventPanel)}`);
  check(adamsEventPanel.includes("sustained reading or later consultation is not"), "documented receipt is overstated as reading");
  await page.locator("#lifeEventPanel .event-documentary-relations button").click();
  await page.locator("#detailLoading").waitFor({ state: "hidden" });
  check(await page.locator("#detailInsights").isVisible(), "question-driven record insights are hidden");
  const adamsRecordInsights = await text(page, "#detailInsightsBody");
  check(adamsRecordInsights.includes("Why is it in this library?"), "record drawer does not answer the membership question");
  check(adamsRecordInsights.toLocaleLowerCase().includes("evidence confidence 98/100"), "record drawer omits documentary confidence");
  check(adamsRecordInsights.includes("sustained reading or later consultation is not"), "record drawer overstates documented interaction");
  await page.locator("#closeDetail").click();
  await page.locator("#activeFilters .active-filter").filter({ hasText: "Life event" }).click();
  await page.waitForFunction(() => !new URL(location.href).searchParams.has("event") && document.querySelector("#resultSummary")?.textContent?.startsWith("4,928 of 4,928"));
  report("life-event graph filters chapter clusters and keeps contextual, documentary, and use claims distinct");

  const staleHistoricalFacetUrl = new URL(page.url());
  staleHistoricalFacetUrl.searchParams.set("lc", "A");
  staleHistoricalFacetUrl.searchParams.set("material", "book");
  staleHistoricalFacetUrl.searchParams.set("decade", "1800");
  await page.goto(staleHistoricalFacetUrl.href, { waitUntil: "domcontentloaded" });
  await ready(page);
  check(!new URL(page.url()).searchParams.has("lc") && !new URL(page.url()).searchParams.has("material") && !new URL(page.url()).searchParams.has("decade"), "undeclared historical facets survived URL normalization");
  const historicalResultSummary = (await page.locator("#resultSummary").textContent() || "").trim();
  check(historicalResultSummary.includes("4,928") && !historicalResultSummary.includes("0 of"), `stale catalog facets silently emptied the historical corpus: ${historicalResultSummary}`);

  const historicalDeepLink = new URL(page.url());
  historicalDeepLink.searchParams.set("record", "jefferson-sowerby-4931");
  await page.goto(historicalDeepLink.href, { waitUntil: "domcontentloaded" });
  await ready(page);
  await page.locator("#detailDrawer.open").waitFor();
  await page.locator("#detailLoading").waitFor({ state: "hidden" });
  const historicalDetail = await text(page, "#detailMetadata");
  check(historicalDetail.includes("ENTITY\nSowerby entry"), "historical drawer does not identify its entity grain");
  check(historicalDetail.includes("SOWERBY NUMBER\n4931"), "historical deep link opened the wrong Sowerby entry");
  check(historicalDetail.includes("SOURCE-BACKED ORDER RANK\n4,928"), "historical dense ordering is not labeled separately from the source serial");
  check(historicalDetail.includes("IDENTIFIER EVIDENCE\n") && !historicalDetail.includes("Source-backed historical Sowerby entry"), "historical identifier evidence is collapsed in the drawer");
  check(historicalDetail.includes("FORMAT\nNot established"), "historical entity type leaked into the material/format field");
  check(historicalDetail.includes("RECONSTRUCTION STATUS\nNot established"), "historical drawer implies a reconstruction status");
  check(await page.locator('#notesList a[href^="https://"][href*="loc.gov"]').count() >= 4, "historical assertion sources are not inspectable LOC links");
  check((await text(page, "#notesList")).includes("Evidence SHA-256: sha256:"), "historical assertion digests are not visible");
  await page.locator("#detailShelfButton").click();
  await page.locator("#closeDetail").click();
  const mixedJeffersonShelf = JSON.parse(await page.evaluate(() => localStorage.getItem("shelfsignals_shelf:jefferson")) || "[]");
  check(mixedJeffersonShelf.includes("jefferson-sowerby-4931") && mixedJeffersonShelf.some(id => id.startsWith("jefferson-loc-")), "Jefferson shelf did not preserve separate corpus IDs");
  report("historical corpus loads 4,928 source-backed entries with gaps, provenance, deep links, and isolated relations");

  const invalidUrl = new URL(baseUrl.href);
  invalidUrl.searchParams.set("collection", "invalid-collection");
  invalidUrl.searchParams.set("corpus", "historical");
  invalidUrl.searchParams.set("order", "sowerby");
  await page.goto(invalidUrl.href, { waitUntil: "domcontentloaded" });
  await ready(page);
  check(await page.locator("#collectionSwitcher").inputValue() === "sekula", "invalid collection did not fall back to Sekula");
  const normalizedInvalid = new URL(page.url());
  check(!normalizedInvalid.searchParams.has("collection") && !normalizedInvalid.searchParams.has("corpus") && !normalizedInvalid.searchParams.has("order"), "invalid collection parameters were not removed");
  report("invalid collection URLs fail safely to canonical Sekula");

  check(pageErrors.length === 0, `browser page errors occurred: ${pageErrors.join(" | ")}`);
  await context.close();

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce", forcedColors: "active" });
  const mobilePage = await mobile.newPage();
  await mobilePage.goto(new URL("?collection=jefferson", baseUrl).href, { waitUntil: "domcontentloaded" });
  await ready(mobilePage);
  check(await mobilePage.locator("#collectionStatusBanner").isVisible(), "mobile beta warning is hidden");
  await assertHeroClearsBanners(mobilePage, "mobile public-mode");
  check(await mobilePage.locator("#orderFilter").isVisible(), "mobile ordering control is inaccessible");
  const overflow = await mobilePage.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(overflow <= 1, `mobile layout overflows by ${overflow}px`);
  check(await mobilePage.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches), "reduced-motion preference is not active");
  await mobilePage.locator("#collectionSwitcher").focus();
  check(await mobilePage.evaluate(() => document.activeElement?.id) === "collectionSwitcher", "collection switcher is not keyboard focusable");
  await mobile.close();
  report("mobile, high-contrast, reduced-motion, and keyboard basics pass");
} finally {
  await browser.close();
}

console.log("Collection browser journey verified.");
