/** Signed file links (FILE_LINK_SECRET is set on the e2e stack). */
import { expect, test } from "@playwright/test";
import { ADMIN, api, cardPost, SITE } from "./support.ts";

test("a signed link loads; unsigned, tampered or expired ones get 403", async ({
  page,
  request,
}) => {
  const id = await cardPost(request, "Lantern Signal");
  const post = await api(request, "GET", `/post/${id}?fields=contentUrl,thumbnailUrl`, {
    user: ADMIN,
  });
  const content = new URL(String(post.body.contentUrl), `${SITE}/`);
  expect(content.searchParams.get("e")).toMatch(/^\d+$/);
  expect(content.searchParams.get("s")).toBeTruthy();

  expect((await request.get(content.href)).status()).toBe(200);
  const unsigned = new URL(content.pathname, SITE);
  expect((await request.get(unsigned.href)).status()).toBe(403);
  const tampered = new URL(content.href);
  const signature = tampered.searchParams.get("s") ?? "";
  tampered.searchParams.set(
    "s",
    `${signature.slice(0, -2)}${signature.endsWith("AA") ? "BB" : "AA"}`,
  );
  expect((await request.get(tampered.href)).status()).toBe(403);
  const expired = new URL(content.href);
  expired.searchParams.set("e", String(Math.floor(Date.now() / 1000) - 60));
  expect((await request.get(expired.href)).status()).toBe(403);

  // in the app: the post's picture, by its signed link, is drawn
  await page.goto(`/posts/${id}`);
  const picture = page.getByRole("main").locator("img").first();
  await expect(picture).toHaveAttribute("src", /[?&]s=/);
  await expect
    .poll(() => picture.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);
});
