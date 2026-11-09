import { randomInt } from "node:crypto";
import { expect, test } from "@playwright/test";
import { picture } from "./cards.ts";
import { ADMIN, api, logIn, upload } from "./support.ts";

test("unlisted stays out of the library, opens by URL, and can be listed", async ({
  page,
  request,
}, testInfo) => {
  const tag = `e2e_listed_${testInfo.project.name}_${randomInt(1000000000)}`;
  const post = await upload(request, `${tag}.png`, picture(randomInt(1000000000)), [
    tag,
  ]);
  const id = post.id as number;
  const unlisted = await api(request, "PUT", `/post/${id}`, {
    user: ADMIN,
    data: { version: post.version, listed: false },
  });
  expect(unlisted.status).toBe(200);
  await logIn(page);
  await page.goto(`/posts?q=${tag}`);
  await expect(page.getByText("Nothing found for", { exact: false })).toBeVisible();
  await expect(page.getByRole("search").getByLabel("Search query")).toHaveValue(tag);
  const found = await api(request, "GET", `/posts?query=${tag}&fields=id`, {
    user: ADMIN,
  });
  expect(found.body.total).toBe(0);
  await page.goto(`/posts/${id}`);
  await expect(page.getByText("Unlisted", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Edit/ }).click();
  await page.getByRole("switch", { name: "Listed" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Unlisted", { exact: true })).toHaveCount(0);
  await page.goto(`/posts?q=${tag}`);
  await expect(
    page
      .getByRole("region", { name: "Results" })
      .locator(`a[href*="/posts/${id}"]`)
      .first(),
  ).toBeVisible();
});
