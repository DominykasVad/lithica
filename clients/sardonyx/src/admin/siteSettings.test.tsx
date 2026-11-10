import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { components } from "@/api/schema";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

type Answer = components["schemas"]["SiteSettings"];
const initial: Answer = {
  version: 1,
  fileLinksSigned: false,
  settings: [
    {
      name: "password_reset_mail_interval",
      type: "integer",
      value: 60,
      startingValue: 120,
      runtime: true,
      stored: true,
      min: 0,
    },
    {
      name: "visibility",
      type: "choice",
      choices: ["open", "login"],
      value: "open",
      startingValue: "open",
      runtime: true,
      stored: false,
    },
    {
      name: "name",
      type: "string",
      value: "Stored title",
      startingValue: "Starting title",
      runtime: true,
      stored: true,
    },
    {
      name: "future_switch",
      type: "boolean",
      value: true,
      startingValue: false,
      runtime: true,
      stored: false,
    },
    {
      name: "modules",
      type: "list",
      value: ["cards"],
      startingValue: ["cards"],
      runtime: false,
      stored: false,
    },
  ],
};
function site(edit = true, conflict = false) {
  sessionStorage.setItem(
    "sardonyx.session",
    JSON.stringify({ user: "ada", token: "login", tokenId: 1 }),
  );
  let answer = initial;
  return fakeSite({
    "GET /info": {
      body: {
        ...INFO,
        config: {
          ...INFO.config,
          privileges: {
            "siteSettings:view": "regular",
            "siteSettings:edit": edit ? "regular" : "administrator",
          },
        },
      },
    },
    "GET /user/ada": { body: { name: "ada", rank: "regular" } },
    "GET /site-settings": () => ({ body: answer }),
    "PUT /site-settings": (sent: Sent) => {
      if (conflict)
        return {
          status: 409,
          body: {
            name: "IntegrityError",
            title: "Conflict",
            description: "Settings changed",
          },
        };
      const body = sent.body as { values: Record<string, unknown> };
      answer = {
        ...initial,
        version: 2,
        settings: initial.settings?.map((item) =>
          item.name && item.name in body.values
            ? ({
                ...item,
                value: body.values[item.name] ?? item.startingValue,
                stored: body.values[item.name] !== null,
              } as typeof item)
            : item,
        ),
      };
      return { body: answer };
    },
  });
}
it("renders server declarations, including unknown settings and restart settings", async () => {
  site();
  renderApp("/admin/settings");
  expect(await screen.findByRole("switch", { name: "future_switch" })).toBeChecked();
  expect(screen.getByText("Set in config.yaml; needs a restart")).toBeInTheDocument();
  expect(screen.getByText("config.yaml: Starting title")).toBeInTheDocument();
});
it("is read-only without edit", async () => {
  site(false);
  renderApp("/admin/settings");
  expect(await screen.findByLabelText("Site name")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Save settings" })).toBeNull();
});
it("sends only changed values and invalidates info", async () => {
  const sent = site();
  renderApp("/admin/settings");
  const input = await screen.findByLabelText("Site name");
  await userEvent.clear(input);
  await userEvent.type(input, "New title");
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await waitFor(() =>
    expect(sent.find((one) => one.method === "PUT")?.body).toEqual({
      version: 1,
      values: { name: "New title" },
    }),
  );
  await waitFor(() =>
    expect(sent.filter((one) => one.path === "/info").length).toBeGreaterThan(1),
  );
});
it("reset sends null", async () => {
  const sent = site();
  renderApp("/admin/settings");
  await userEvent.click(await screen.findByRole("button", { name: "Reset Site name" }));
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await waitFor(() =>
    expect(sent.find((one) => one.method === "PUT")?.body).toEqual({
      version: 1,
      values: { name: null },
    }),
  );
});
it("offers Reload on 409 and discards the draft", async () => {
  site(true, true);
  renderApp("/admin/settings");
  await userEvent.click(await screen.findByRole("switch", { name: "future_switch" }));
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await userEvent.click(await screen.findByRole("button", { name: "Reload" }));
  await waitFor(() =>
    expect(screen.getByRole("switch", { name: "future_switch" })).toBeChecked(),
  );
});
it("warns about unsigned file links beside non-open visibility", async () => {
  site();
  renderApp("/admin/settings");
  await userEvent.click(await screen.findByRole("radio", { name: "login" }));
  expect(screen.getByText(/Post files stay reachable/)).toBeInTheDocument();
});
it.each([true, false])("menu entry follows view privilege: %s", async (view) => {
  site();
  if (!view)
    fakeSite({
      "GET /info": { body: INFO },
      "GET /user/ada": { body: { name: "ada", rank: "regular" } },
    });
  renderApp("/account");
  await userEvent.click(await screen.findByRole("button", { name: "ada" }));
  await waitFor(() =>
    expect(Boolean(screen.queryByRole("menuitem", { name: "Site settings" }))).toBe(
      view,
    ),
  );
});

it("keeps an emptied integer blank and excludes it from saves", async () => {
  const sent = site();
  renderApp("/admin/settings");
  const interval = await screen.findByRole("spinbutton", {
    name: "Password reset mail interval",
  });
  await userEvent.clear(interval);
  expect(interval).toHaveValue(null);
  expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
  await userEvent.type(interval, "30");
  expect(interval).toHaveValue(30);
  await userEvent.clear(interval);
  await userEvent.click(screen.getByRole("switch", { name: "future_switch" }));
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await waitFor(() =>
    expect(sent.find((one) => one.method === "PUT")?.body).toEqual({
      version: 1,
      values: { future_switch: false },
    }),
  );
});

it("sends an explicit zero and resets an integer draft to config.yaml", async () => {
  const sent = site();
  renderApp("/admin/settings");
  const interval = await screen.findByRole("spinbutton", {
    name: "Password reset mail interval",
  });
  await userEvent.clear(interval);
  await userEvent.type(interval, "0");
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await waitFor(() =>
    expect(sent.find((one) => one.method === "PUT")?.body).toEqual({
      version: 1,
      values: { password_reset_mail_interval: 0 },
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled(),
  );
  const next = screen.getByRole("spinbutton", { name: "Password reset mail interval" });
  await userEvent.clear(next);
  await userEvent.click(
    screen.getByRole("button", { name: "Reset Password reset mail interval" }),
  );
  expect(next).toHaveValue(120);
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await waitFor(() =>
    expect(sent.filter((one) => one.method === "PUT")[1]?.body).toEqual({
      version: 2,
      values: { password_reset_mail_interval: null },
    }),
  );
});
