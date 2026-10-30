/**
 * A password reset from end to end, with the mail the site sends (read from
 * the stack's mail catcher): the link, the new password, logging in with it
 * and changing it. The link's token is in no log of the run.
 */
import { type APIRequestContext, expect, test } from "@playwright/test";
import { api, compose, ensureUser, MAIL, SITE } from "./support.ts";

/** The text of the newest mail to this address, once it is there. */
async function mailTo(request: APIRequestContext, address: string): Promise<string> {
  let id = "";
  await expect
    .poll(
      async () => {
        const found = await request.get(
          `${MAIL}/api/v1/search?query=${encodeURIComponent(`to:"${address}"`)}`,
        );
        const messages = (await found.json()).messages as { ID: string }[];
        id = messages[0]?.ID ?? "";
        return id;
      },
      { timeout: 30_000 },
    )
    .not.toBe("");
  const message = await request.get(`${MAIL}/api/v1/message/${id}`);
  return String((await message.json()).Text);
}

async function canLogIn(request: APIRequestContext, name: string, password: string) {
  const answer = await api(request, "GET", `/user/${name}`, {
    user: { name, password },
  });
  return answer.status === 200;
}

test("forgot the password: mail, link, new password, log in, change it", async ({
  page,
  request,
}, testInfo) => {
  const user = {
    name: `reset_${testInfo.project.name}_${Date.now()}`,
    password: "first-pass-1",
    email: "",
  };
  user.email = `${user.name}@example.com`;
  await ensureUser(request, user);

  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await page.getByLabel("User name or email").fill(user.email);
  await page.getByRole("button", { name: "Send me a link" }).click();
  await expect(page.getByRole("status")).toContainText(
    "a link to reset its password is on its way",
  );

  const text = await mailTo(request, user.email);
  const link = text.match(new RegExp(`${SITE}/password-reset/\\S+`))?.[0];
  expect(link, text).toBeTruthy();
  const token = (link ?? "").slice((link ?? "").lastIndexOf(":") + 1);
  expect(token.length).toBeGreaterThan(16);

  // the link: its token is off the address at once
  await page.goto(link ?? "");
  await expect(page).toHaveURL(`${SITE}/password-reset/confirm`);
  expect(page.url()).not.toContain(token);
  await page.getByRole("button", { name: "Reset the password" }).click();
  const field = page.getByLabel("New password");
  await expect(field).not.toHaveValue("");
  const generated = await field.inputValue();

  // log in with it, and change it at once
  await page.getByRole("link", { name: "Log in and change it now" }).click();
  await page.getByLabel("User name").fill(user.name);
  await page.getByLabel("Password").fill(generated);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(`${SITE}/account`);
  await page.getByLabel("Current password").fill(generated);
  await page.getByLabel("New password").fill("second-pass-2");
  await page.getByRole("button", { name: "Change the password" }).click();
  await expect(page.getByRole("status")).toHaveText("Your password is changed.");

  // the first and the generated one no longer work, the new one does
  expect(await canLogIn(request, user.name, user.password)).toBe(false);
  expect(await canLogIn(request, user.name, generated)).toBe(false);
  expect(await canLogIn(request, user.name, "second-pass-2")).toBe(true);

  // the token is in no log of this run: not Sardonyx's access log, not the
  // server's; the access log is there and has the run's other requests
  const sardonyx = compose("logs", "--no-color", "sardonyx");
  expect(sardonyx).toContain("GET /login");
  expect(sardonyx).not.toContain(token);
  expect(compose("logs", "--no-color", "server")).not.toContain(token);
});
