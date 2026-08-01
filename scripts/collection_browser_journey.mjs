#!/usr/bin/env node

import fs from "node:fs";

const baseUrl = new URL(process.argv[2] || "http://127.0.0.1:8000/");
const playwrightModule = process.env.SHELFSIGNALS_PLAYWRIGHT_MODULE || "playwright";
const chromeExecutable = process.env.SHELFSIGNALS_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

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
  check(await text(page, "#collectionCount") === "2,748", "Jefferson catalog-instance count is wrong");
  check((await text(page, "#collectionStatusText")).includes("not the complete 4,931-entry Sowerby corpus"), "beta coverage warning is incomplete");
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
