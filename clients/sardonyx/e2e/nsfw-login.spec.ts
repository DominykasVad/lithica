/**
 * A site in nsfw-login (the e2e stack's second site, on the same posts): a
 * visitor who is not logged in finds no NSFW post, by search or by address;
 * a logged-in user does.
 */
import { expect, test } from "@playwright/test";
import { ADMIN, api, cardPost, logIn, NSFW_SITE } from "./support.ts";

test.use({ baseURL: NSFW_SITE });

test("a visitor sees no NSFW post, by search or by address", async ({
  page,
  request,
}) => {
  const night = await cardPost(request, "Night Shift");
  const info = await api(request, "GET", "/info", { site: NSFW_SITE });
  expect(info.body.visibility).toBe("nsfw-login");

  await page.goto("/posts?q=e2e_maker");
  const results = page.getByRole("region", { name: "Results" });
  await expect(results.getByText("Harbour Keeper")).toBeVisible();
  await expect(results.getByText("Night Shift")).toHaveCount(0);

  await page.goto("/posts?q=nsfw");
  await expect(page.getByText("Nothing found for")).toBeVisible();

  await page.goto(`/posts/${night}`);
  await expect(page.getByRole("heading", { name: `Post ${night}` })).toBeVisible();
  await expect(page.getByText(/not found/i).first()).toBeVisible();
  await expect(page.getByText("Night Shift")).toHaveCount(0);

  // the card and its download are not there either
  for (const path of [
    `/modules/cards/post/${night}`,
    `/modules/cards/post/${night}/download`,
  ]) {
    expect((await api(request, "GET", path, { site: NSFW_SITE })).status, path).toBe(
      404,
    );
  }
});

test("a logged-in user sees them", async ({ page, request }) => {
  const night = await cardPost(request, "Night Shift");
  await logIn(page, ADMIN);
  await page.goto(`/posts/${night}`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Night Shift" }),
  ).toBeVisible();
});
