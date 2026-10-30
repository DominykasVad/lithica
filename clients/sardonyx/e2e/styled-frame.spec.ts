/**
 * Styled card text in its frame: the card's HTML and CSS are drawn, but its
 * scripts do not run, it reaches neither the app's page nor its storage, and
 * no picture of it is asked for before the viewer asks.
 */
import { expect, test } from "@playwright/test";
import { cardPost } from "./support.ts";

const IMAGE_HOST = "e2e-images.example";

test("the frame draws the card, and lets nothing of it out", async ({
  page,
  request,
}) => {
  const id = await cardPost(request, "Styled Probe");
  // The card's pictures that went out: finished, or failed for a reason
  // other than the frame's policy (the host does not exist). Chromium also
  // reports a load the policy stopped, as a request that failed with "csp";
  // nothing of it reached the network.
  const pictures: string[] = [];
  page.on("requestfinished", (one) => {
    if (one.url().includes(IMAGE_HOST)) {
      pictures.push(one.url());
    }
  });
  page.on("requestfailed", (one) => {
    if (one.url().includes(IMAGE_HOST) && one.failure()?.errorText !== "csp") {
      pictures.push(one.url());
    }
  });
  // what the page is sent by message, from anywhere
  await page.addInitScript(() => {
    const seen: unknown[] = [];
    (window as unknown as { seen: unknown[] }).seen = seen;
    window.addEventListener("message", (event) => seen.push(event.data));
  });
  await page.goto(`/posts/${id}`);
  await page
    .getByRole("group", { name: "Card text" })
    .getByRole("button", { name: "Styled" })
    .click();

  const frame = page.frameLocator('iframe[title="Card text, styled"]');
  const text = frame.getByText("Styled probe text");
  await expect(text).toBeVisible();
  // its own styles apply
  await expect(text).toHaveCSS("color", "rgb(200, 30, 30)");

  // give the card's scripts (were they to run) the time to try
  await page.waitForTimeout(1500);
  const seen = await page.evaluate(
    () => (window as unknown as { seen: unknown[] }).seen,
  );
  // only the frame's own message (its height), nothing of the card's
  expect(seen.filter((one) => typeof one === "string")).toEqual([]);
  expect(JSON.stringify(seen)).not.toContain("probe");
  await expect(page).not.toHaveTitle("probe");
  expect(await page.evaluate(() => localStorage.getItem("probe"))).toBeNull();
  // and no picture of the card was asked for
  expect(pictures).toEqual([]);

  // the viewer asks: now the card's picture is asked for, from the frame
  await page.getByRole("button", { name: `Load images from ${IMAGE_HOST}` }).click();
  await expect.poll(() => pictures).toEqual([`https://${IMAGE_HOST}/probe.png`]);
  await page.waitForTimeout(1000);
  expect(
    JSON.stringify(
      await page.evaluate(() => (window as unknown as { seen: unknown[] }).seen),
    ),
  ).not.toContain("probe");
  expect(await page.evaluate(() => localStorage.getItem("probe"))).toBeNull();
});
