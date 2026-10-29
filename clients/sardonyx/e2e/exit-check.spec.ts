/**
 * The phase-5 exit check of PLAN.md, one test per step, in each browser.
 * Its first step, importing the sample cards, is in stack.setup.ts (once,
 * before the browsers).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { picture, zipBomb } from "./cards.ts";
import {
  ADMIN,
  cardPost,
  LARGE_ENTRIES,
  LARGE_LOREBOOK,
  logIn,
  postId,
} from "./support.ts";

const FIXTURES = path.join(import.meta.dirname, "fixtures", "cards");

test.describe.configure({ mode: "serial" });

const results = (page: Page) => page.getByRole("region", { name: "Results" });

async function search(page: Page, query: string) {
  const box = page.getByRole("search").getByLabel("Search query");
  await box.fill(query);
  await page.getByRole("search").getByRole("button", { name: "Search" }).click();
}

test("log in", async ({ page }) => {
  await logIn(page);
  // the session lasts a reload of the tab
  await page.reload();
  await expect(
    page.getByRole("banner").getByRole("button", { name: ADMIN.name }),
  ).toBeVisible();
});

test("search with text and card filters", async ({ page }) => {
  await logIn(page);
  await page.goto("/posts");
  await search(page, "e2e_maker");
  // the creator's tag: the four cards of e2e_maker (not Tidewarden)
  await expect(results(page).getByText("Harbour Keeper")).toBeVisible();
  await expect(results(page).getByText("Tidewarden")).toHaveCount(0);

  // a filter writes into the search line; V3 leaves the V2 cards out
  const filters = page.getByRole("complementary", { name: "Card filters" });
  await filters.getByLabel("V3").check();
  await expect(page.getByRole("search").getByLabel("Search query")).toHaveValue(
    /card-spec:v3/,
  );
  await expect(results(page).getByText("Lantern Signal")).toBeVisible();
  await expect(results(page).getByText("Harbour Keeper")).toHaveCount(0);

  // the file filter: CHARX alone finds Tidewarden
  await search(page, "");
  await filters.getByLabel("CHARX").check();
  await expect(results(page).getByText("Tidewarden")).toBeVisible();
  await expect(results(page).getByText("Lantern Signal")).toHaveCount(0);
});

for (const [name, spec, format] of [
  ["Harbour Keeper", "V2", "PNG"],
  ["Lantern Signal", "V3", "PNG"],
  ["Tidewarden", "V3", "CHARX"],
] as const) {
  test(`open a ${spec} ${format} card: ${name}`, async ({ page, request }) => {
    const id = await cardPost(request, name);
    await logIn(page);
    await page.goto(`/posts/${id}`);
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    const facts = page.locator("dl").filter({ hasText: "Spec" });
    await expect(facts).toContainText(spec);
    await expect(facts).toContainText(format);
    await expect(page.getByRole("tablist", { name: "Card sections" })).toBeVisible();
    await expect(page).toHaveTitle(`${name} · Sardonyx`);
  });
}

test("read the greetings and a large lorebook", async ({ page, request }) => {
  const keeper = await cardPost(request, "Harbour Keeper");
  await logIn(page);
  await page.goto(`/posts/${keeper}`);
  // the first message and three alternate ones, one at a time
  await page.getByRole("tab", { name: "Greetings (4)" }).click();
  await expect(page.getByText("Harbour Keeper looks up from the")).toBeVisible();
  await page.getByRole("button", { name: "Next greeting" }).click();
  await expect(page.getByText(/^Greeting 2:/)).toBeVisible();

  const archive = await cardPost(request, LARGE_LOREBOOK);
  await page.goto(`/posts/${archive}/lorebook`);
  await expect(
    page.getByText(`${LARGE_ENTRIES.toLocaleString("en")} entries`).first(),
  ).toBeVisible();
  // a virtual list: a few rows drawn, not 2500
  const rows = await page.getByText(/^Entry \d+$/).count();
  expect(rows).toBeGreaterThan(0);
  expect(rows).toBeLessThan(200);
  // the filter finds one far down the list
  await page
    .getByLabel("Filter entries by key, name, comment or content")
    .fill("Entry 2417:");
  await expect(page.getByText("Entry 2417", { exact: true })).toBeVisible();
  expect(await page.getByText(/^Entry \d+$/).count()).toBe(1);
});

test("download a card", async ({ page, request }) => {
  const id = await cardPost(request, "Harbour Keeper");
  await logIn(page);
  await page.goto(`/posts/${id}`);
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download Harbour Keeper.png" }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("Harbour Keeper.png");
  const saved = readFileSync(await download.path());
  // the card as it was imported, byte for byte
  expect(saved.equals(readFileSync(path.join(FIXTURES, "harbour-keeper-v2.png")))).toBe(
    true,
  );
});

test("upload new files, and see a hostile ZIP refused", async ({ page }, testInfo) => {
  await logIn(page);
  await page.goto("/upload");
  // a picture no run has uploaded yet, and a ZIP bomb in a card's clothes
  const fresh = picture((Date.now() % 1_000_000_000) + testInfo.workerIndex);
  await page.getByRole("combobox", { name: /^Tags/ }).fill("e2e_uploaded");
  await page.locator('input[type="file"]').setInputFiles([
    { name: "fresh.png", mimeType: "image/png", buffer: fresh },
    { name: "hostile.charx", mimeType: "application/zip", buffer: zipBomb() },
  ]);
  await page.getByRole("button", { name: "Upload 2 files" }).click();
  await expect(page.getByText("Created:")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("link", { name: /^post \d+$/ })).toHaveCount(1);
  // the bomb: refused by the site, for what it is
  await expect(page.getByText(/^Refused/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/compressed more than 100:1/)).toBeVisible();
});

test("edit tags", async ({ page, request }, testInfo) => {
  const id = await cardPost(request, "Lantern Signal");
  // new on every run: a run again on the same stack changes something too
  const tag = `e2e_edited_${testInfo.project.name}_${Date.now()}`;
  await logIn(page);
  await page.goto(`/posts/${id}`);
  await page.getByRole("button", { name: /^Edit / }).click();
  const tags = page.getByRole("main").getByRole("textbox", { name: /^Tags/ });
  await expect(tags).toBeFocused();
  await tags.fill(`${await tags.inputValue()} ${tag}`);
  await page.getByRole("button", { name: "Save" }).click();
  // saved: the editor closes, and the tag is among the post's (its name, then
  // how many posts have it)
  await expect(tags).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: new RegExp(`^${tag} \\d+$`) }),
  ).toBeVisible();
  // the site has it: a search for the tag finds the post
  expect(await postId(request, tag)).toBe(id);
});

test("log out", async ({ page }) => {
  await logIn(page);
  await page.getByRole("banner").getByRole("button", { name: ADMIN.name }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await expect(
    page.getByRole("banner").getByRole("link", { name: "Log in" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("banner").getByRole("link", { name: "Log in" }),
  ).toBeVisible();
});
