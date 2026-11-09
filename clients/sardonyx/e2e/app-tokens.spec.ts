/**
 * App tokens (phase 6.1): one made on the account page reads as its rights
 * allow and nothing more, and stops working when it is revoked there.
 */
import { type APIRequestContext, expect, test } from "@playwright/test";
import { ensureUser, logIn, SITE } from "./support.ts";

const OWNER = { name: "e2e_app_owner", password: "e2e-app-owner-pass" };

// a list of posts, as small as it can be: what the token may do is the
// point, and the whole resource of a hundred posts takes long on this site
const LIST_POSTS = "/posts?limit=1&fields=id";

const tokenHeader = (value: string) =>
  `Token ${Buffer.from(`${OWNER.name}:${value}`).toString("base64")}`;

async function withToken(
  request: APIRequestContext,
  value: string,
  method: string,
  route: string,
  multipart?: Record<string, { name: string; mimeType: string; buffer: Buffer }>,
): Promise<{ status: number; name: unknown }> {
  const response = await request.fetch(`${SITE}/api${route}`, {
    method,
    headers: { Accept: "application/json", Authorization: tokenHeader(value) },
    multipart,
    maxRedirects: 0,
  });
  const body = (await response.json()) as { name?: unknown };
  return { status: response.status(), name: body.name };
}

test("a read token reads, may not upload, and stops when revoked", async ({
  page,
  request,
}, testInfo) => {
  await ensureUser(request, OWNER);
  await logIn(page, OWNER);
  await page.goto("/account");

  const name = `e2e reader ${testInfo.project.name} ${Date.now()}`;
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Read", { exact: true }).check();
  await page.getByRole("button", { name: "Make the token" }).click();
  const shown = page.getByLabel("The new token");
  await expect(shown).toHaveValue(/^lithica_app_/);
  const value = await shown.inputValue();
  await expect(page.getByText(/won't be shown again/)).toBeVisible();

  // read: posts are listed; upload: refused, the token being fine
  expect(await withToken(request, value, "GET", LIST_POSTS)).toEqual({
    status: 200,
    name: undefined,
  });
  expect(
    await withToken(request, value, "POST", "/uploads", {
      content: {
        name: "a.txt",
        mimeType: "application/octet-stream",
        buffer: Buffer.from("hello"),
      },
    }),
  ).toEqual({ status: 403, name: "AuthError" });

  await page.getByRole("button", { name: "Done" }).click();
  const item = page.getByRole("listitem").filter({ hasText: name });
  await item.getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("button", { name: `Revoke “${name}”` }).click();
  await expect(page.getByRole("listitem").filter({ hasText: name })).toHaveCount(0);

  expect(await withToken(request, value, "GET", LIST_POSTS)).toEqual({
    status: 403,
    name: "InvalidTokenError",
  });
});
