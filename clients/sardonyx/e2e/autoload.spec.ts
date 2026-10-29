/**
 * Auto load in a real browser: opening the list at a place, and coming back
 * to it from a post. (jsdom has no layout: the unit tests stand in for the
 * window's scrolling.)
 */
import { expect, type Page, test } from "@playwright/test";
import { BULK_COUNT, BULK_TAG } from "./support.ts";

// a row of posts without cards at the tests' 1280 px: 240 + 8 + 20, and 20 between
const ROW_AT_1280 = 288;

/** The "n of total" of the list, and where the window is. */
async function where(page: Page) {
  const counter = page.getByText(new RegExp(`^\\d+ of ${BULK_COUNT}$`));
  await expect(counter).toBeVisible();
  return {
    counter: await counter.textContent(),
    scrollY: await page.evaluate(() => Math.round(window.scrollY)),
  };
}

test("opens at `at`, and comes back there from a post", async ({ page }) => {
  await page.goto(`/posts?q=${BULK_TAG}&at=120`);
  // the batch that holds 120 (the second), scrolled to: 121 at the top
  await expect(page.getByText(`121 of ${BULK_COUNT}`)).toBeVisible();
  const opened = await where(page);
  expect(opened.scrollY).toBeGreaterThan(0);

  // scroll a little further, let the place settle into the address
  await page.evaluate(() => window.scrollBy(0, 700));
  await expect(page).not.toHaveURL(/at=120\b/);
  // the place in the address is the first result in view, once scrolling
  // has rested (a scroll may arrive in steps: wait for the last)
  const scrolled = await where(page);
  const first = Number(scrolled.counter?.split(" ")[0]) - 1;
  await expect(page).toHaveURL(new RegExp(`at=${first}$`));

  // a post, then back
  // a tile in view: one of the rows drawn above it (the list draws a few
  // beyond the window) would be scrolled to first, and that is a new place
  const tiles = page.getByRole("region", { name: "Results" }).getByRole("link");
  const inView = await tiles.evaluateAll((links) =>
    links.findIndex((link) => link.getBoundingClientRect().top >= 0),
  );
  await tiles.nth(inView).click();
  await expect(page).toHaveURL(/\/posts\/\d+/);
  await page.goBack();
  await expect(page).toHaveURL(/\/posts\?/);
  await expect(page.getByText(scrolled.counter ?? "")).toBeVisible();
  const back = await where(page);
  // the same first result in view, its row at the top: `at` is a result,
  // and the list opens at the start of its row
  expect(back.counter).toBe(scrolled.counter);
  expect(back.scrollY).toBeLessThanOrEqual(scrolled.scrollY);
  expect(scrolled.scrollY - back.scrollY).toBeLessThan(ROW_AT_1280);
});

test("shows the start of the list when scrolled up to it", async ({ page }) => {
  await page.goto(`/posts?q=${BULK_TAG}&at=120`);
  await expect(page.getByText(`121 of ${BULK_COUNT}`)).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page.getByText(`1 of ${BULK_COUNT}`)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`\\?q=${BULK_TAG}$`));
  // the first tiles, with their pictures (by their signed links)
  const first = page.getByRole("region", { name: "Results" }).locator("img").first();
  await expect(first).toBeVisible();
  await expect
    .poll(() => first.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);
});
