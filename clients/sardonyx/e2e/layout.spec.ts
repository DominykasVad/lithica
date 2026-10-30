/** No page of the app scrolls sideways on a phone (375 px). */
import { expect, test } from "@playwright/test";
import {
  BULK_TAG,
  cardPost,
  LARGE_LOREBOOK,
  logIn,
  postId,
  scrollsSideways,
} from "./support.ts";

test.use({ viewport: { width: 375, height: 812 }, isMobile: false });

test("the main pages do not scroll sideways at 375 px", async ({ page, request }) => {
  const card = await cardPost(request, "Harbour Keeper");
  const archive = await cardPost(request, LARGE_LOREBOOK);
  const picture = await postId(request, BULK_TAG);
  await logIn(page);
  for (const path of [
    "/",
    "/posts",
    `/posts?q=${BULK_TAG}`,
    `/posts/${card}`,
    `/posts/${card}?tab=lorebook`,
    `/posts/${archive}/lorebook`,
    `/posts/${picture}`,
    "/upload",
    "/tags",
    "/account",
  ]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(await scrollsSideways(page), path).toBe(false);
  }
  // and those of a visitor who is not logged in
  await page.getByRole("banner").getByRole("button", { name: "e2e_admin" }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  for (const path of ["/login", "/password-reset"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(await scrollsSideways(page), path).toBe(false);
  }
});
