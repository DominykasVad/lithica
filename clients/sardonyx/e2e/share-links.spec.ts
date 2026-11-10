/** Bearer delivery is checked by the API and served by nginx. */
import { randomInt } from "node:crypto";
import { expect, test } from "@playwright/test";
import { charxCard, picture, pngCard, v3Card } from "./cards.ts";
import { ADMIN, api, compose, logIn, NSFW_SITE, SITE, upload } from "./support.ts";

for (const kind of ["picture", "png", "charx"] as const) {
  test(`a ${kind} share delivers the original bytes and MIME type`, async ({
    request,
  }) => {
    const seed = randomInt(1_000_000);
    const card = v3Card({ name: `Share ${kind}`, creator: "Lithica tests" });
    const bytes =
      kind === "picture"
        ? picture(seed)
        : kind === "png"
          ? pngCard(card, seed)
          : charxCard(card, seed);
    const post = await upload(
      request,
      `share.${kind === "charx" ? "charx" : "png"}`,
      bytes,
    );
    const made = await api(request, "POST", `/post/${post.id}/share-links`, {
      user: ADMIN,
      data: {},
    });
    expect(made.status).toBe(200);
    const url = new URL(String(made.body.url), SITE).href;
    const response = await request.get(url);
    expect(response.status()).toBe(200);
    expect(await response.body()).toEqual(bytes);
    const token = new URL(url).pathname.split("/").at(-1) ?? "";
    expect((await request.get(`${SITE}/api/share/${token}`)).status()).toBe(404);
    expect(compose("logs", "sardonyx", "server")).not.toContain(token);
    expect(response.headers()["content-type"]).toBe(
      kind === "charx" ? "application/x-charx" : "image/png",
    );
    const filename = new URL(String(post.contentUrl), SITE).pathname.split("/").at(-1);
    expect((await request.get(`${SITE}/_share/${filename}`)).status()).toBe(404);
    expect(
      (await api(request, "DELETE", `/share-link/${made.body.id}`, { user: ADMIN }))
        .status,
    ).toBe(200);
    expect((await request.get(url)).status()).toBe(404);
  });
}

test("an NSFW share is refused on the nsfw-login site", async ({ request }) => {
  const post = await upload(request, "nsfw-share.png", picture(randomInt(1_000_000)));
  const made = await api(request, "POST", `/post/${post.id}/share-links`, {
    user: ADMIN,
    data: {},
  });
  expect(made.status).toBe(200);
  expect(
    (
      await api(request, "PUT", `/post/${post.id}`, {
        user: ADMIN,
        data: { version: post.version, tags: ["nsfw"] },
      })
    ).status,
  ).toBe(200);
  const path = new URL(String(made.body.url), SITE).pathname;
  expect((await request.get(`${NSFW_SITE}${path}`)).status()).toBe(404);
});

test("share links can be created, found on the account and revoked in Sardonyx", async ({
  page,
  request,
}) => {
  const bytes = picture(randomInt(1_000_000));
  const post = await upload(request, "ui-share.png", bytes);
  await logIn(page);
  await page.goto(`/posts/${post.id}`);
  const section = page.getByRole("region", { name: "Share links" });
  const note = `UI share ${post.id}`;
  await section.getByLabel("Note (optional)").fill(note);
  await section.getByRole("button", { name: "Create link" }).click();
  const row = section.getByRole("listitem").filter({ hasText: note });
  const field = row.getByLabel("Share link URL");
  await expect(field).toBeVisible();
  const url = await field.inputValue();
  const file = await request.get(url);
  expect(file.status()).toBe(200);
  expect(await file.body()).toEqual(bytes);
  await page.goto("/account");
  const accountRow = page
    .getByRole("list", { name: "Your share links" })
    .getByRole("listitem")
    .filter({ hasText: note });
  await expect(
    accountRow.getByRole("link", { name: `Post ${post.id}`, exact: true }),
  ).toBeVisible();
  await page.goto(`/posts/${post.id}`);
  await row.getByRole("button", { name: "Revoke", exact: true }).click();
  await row.getByRole("button", { name: "Confirm revoke" }).click();
  await expect(row).toHaveCount(0);
  expect((await request.get(url)).status()).toBe(404);
});
