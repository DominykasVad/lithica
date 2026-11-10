import { expect, test } from "@playwright/test";
import type { components } from "../src/api/schema.ts";
import { ADMIN, api, logIn, NSFW_SITE, SITE } from "./support.ts";

type Settings = components["schemas"]["SiteSettings"];

test.afterEach(async ({ request }) => {
  const current = await api(request, "GET", "/site-settings", { user: ADMIN });
  expect(current.status).toBe(200);
  const reset = await api(request, "PUT", "/site-settings", {
    user: ADMIN,
    data: {
      version: current.body.version,
      values: { visibility: null, "features.pools": null },
    },
  });
  expect(reset.status).toBe(200);
  const final = await api(request, "GET", "/site-settings", { user: ADMIN });
  expect((final.body as Settings).settings?.filter((item) => item.stored)).toEqual([]);
});

test("changes visibility and pools immediately on both servers", async ({
  page,
  browser,
  request,
}) => {
  await logIn(page);
  await page.goto("/admin/settings");
  await page.getByRole("radio", { name: "login", exact: true }).check();
  const savedVisibility = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/site-settings") &&
      response.request().method() === "PUT",
  );
  await page.getByRole("button", { name: "Save settings" }).click();
  expect((await savedVisibility).status()).toBe(200);
  await expect(page.getByRole("button", { name: "Save settings" })).toBeDisabled();

  const anonymous = await browser.newContext();
  try {
    const visitor = await anonymous.newPage();
    for (const site of [SITE, NSFW_SITE]) {
      await visitor.goto(site);
      await expect(visitor.getByLabel("User name")).toBeVisible();
      await expect(visitor.getByRole("region", { name: "Results" })).toHaveCount(0);
      const info = await api(request, "GET", "/info", { site });
      expect(info.body.visibility).toBe("login");
    }
  } finally {
    await anonymous.close();
  }

  await page.getByRole("switch", { name: "Pools", exact: true }).uncheck();
  const savedPools = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/site-settings") &&
      response.request().method() === "PUT",
  );
  await page.getByRole("button", { name: "Save settings" }).click();
  expect((await savedPools).status()).toBe(200);
  await expect(page.getByRole("button", { name: "Save settings" })).toBeDisabled();
  for (const site of [SITE, NSFW_SITE]) {
    const info = await api(request, "GET", "/info", { user: ADMIN, site });
    expect(info.body.features, site).toMatchObject({ pools: false });
    const pools = await api(request, "GET", "/pools", { user: ADMIN, site });
    expect(pools.status).toBe(404);
    expect(pools.body.name).toBe("FeatureDisabledError");
  }
});
