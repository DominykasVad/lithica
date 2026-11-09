import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

const TOKEN = "the-login-token";
const VALUE = "lithica_app_ThisIsTheOneTimeValueOfTheNewToken00000000";

const PRIVILEGES = {
  "appTokens:list:self": "regular",
  "appTokens:create:self": "regular",
  "appTokens:delete:self": "regular",
};
const RIGHTS = {
  read: ["posts:list", "posts:view", "tags:list"],
  write: ["posts:create:identified", "posts:edit:tags"],
  upload: ["uploads:create"],
};

const LISTED = {
  id: 5,
  user: { name: "ada" },
  name: "Lumiverse",
  rights: ["read"],
  token: null,
  enabled: true,
  expirationTime: "2027-01-31T22:59:59Z",
  creationTime: "2026-11-01T10:00:00Z",
  lastEditTime: null,
  lastUsageTime: null,
  version: 1,
};

function logged(
  routes: Record<string, unknown> = {},
  privileges: Record<string, string> = PRIVILEGES,
) {
  sessionStorage.setItem(
    "sardonyx.session",
    JSON.stringify({ user: "ada", token: TOKEN, tokenId: 1 }),
  );
  let tokens = [LISTED];
  return fakeSite({
    "GET /info": {
      body: {
        ...INFO,
        appTokenRights: RIGHTS,
        config: { ...INFO.config, privileges },
      },
    },
    "GET /posts": { body: { total: 0, results: [] } },
    "GET /user/ada": { body: { name: "ada", version: 7, rank: "regular" } },
    "GET /app-tokens/ada": () => ({ body: { results: tokens } }),
    "POST /app-token/ada": (sent: Sent) => {
      const body = sent.body as { name: string; rights: string[] };
      const made = { ...LISTED, id: 6, name: body.name, rights: body.rights };
      tokens = [...tokens, made];
      return { body: { ...made, token: VALUE } };
    },
    "DELETE /app-token/ada/5": () => {
      tokens = tokens.filter((one) => one.id !== 5);
      return { body: {} };
    },
    ...routes,
  } as never);
}

describe("app tokens on the account page", () => {
  it("lists the tokens with their rights and dates", async () => {
    logged();
    renderApp("/account");
    const list = await screen.findByRole("list", { name: "Your app tokens" });
    const item = within(list).getByRole("listitem");
    expect(item).toHaveTextContent("Lumiverse");
    expect(item).toHaveTextContent("Read");
    expect(item).toHaveTextContent("Created");
    expect(item).toHaveTextContent("Nov 1, 2026");
    expect(item).toHaveTextContent("Last used");
    expect(item).toHaveTextContent("never");
    expect(item).toHaveTextContent("Enabled");
  });

  it("is not shown without the privilege to list them", async () => {
    logged({}, {});
    renderApp("/account");
    expect(await screen.findByLabelText("Current password")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "App tokens" })).toBeNull();
  });

  it("makes a token with the rights checked, shows its value once, then forgets it", async () => {
    const sent = logged();
    const view = renderApp("/account");
    const user = userEvent.setup();
    // the rights from GET /info, each with the privileges it carries
    expect(await screen.findByText(/posts:create:identified/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Name"), "Lumiverse plugin");
    await user.click(screen.getByLabelText("Read"));
    await user.click(screen.getByLabelText("Upload"));
    await user.click(screen.getByRole("button", { name: "Make the token" }));

    const shown = await screen.findByLabelText("The new token");
    expect(shown).toHaveValue(VALUE);
    expect(shown).toHaveFocus();
    expect(screen.getByText(/won't be shown again/)).toBeInTheDocument();
    const post = sent.find((one: Sent) => one.method === "POST");
    expect(post?.body).toEqual({
      name: "Lumiverse plugin",
      rights: ["read", "upload"],
    });

    // held by the view only: not in the queries, storage or the address
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    const cached = JSON.stringify(
      view.queryClient
        .getQueryCache()
        .getAll()
        .map((query) => query.state.data),
    );
    expect(cached).not.toContain(VALUE);
    expect(JSON.stringify({ ...sessionStorage, ...localStorage })).not.toContain(VALUE);
    expect(view.router.state.location.href).not.toContain(VALUE);

    // leaving the view forgets it
    await view.router.navigate({ to: "/posts" });
    await view.router.navigate({ to: "/account" });
    expect(
      await screen.findByRole("button", { name: "Make the token" }),
    ).toBeInTheDocument();
    expect(screen.queryByDisplayValue(VALUE)).toBeNull();
    expect(document.body.innerHTML).not.toContain(VALUE);
  });

  it("forgets the value on Done", async () => {
    logged();
    renderApp("/account");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Name"), "x");
    await user.click(screen.getByLabelText("Read"));
    await user.click(screen.getByRole("button", { name: "Make the token" }));
    await screen.findByLabelText("The new token");
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(document.body.innerHTML).not.toContain(VALUE);
  });

  it("shows the site's refusal of a token without rights", async () => {
    logged({
      "POST /app-token/ada": {
        status: 400,
        body: {
          name: "InvalidAppTokenRightsError",
          title: "Bad request",
          description: "An app token needs at least one right.",
        },
      },
    });
    renderApp("/account");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Name"), "x");
    await user.click(screen.getByRole("button", { name: "Make the token" }));
    expect(
      await screen.findByText("An app token needs at least one right."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("The new token")).toBeNull();
  });

  it("revokes a token after a confirmation that names it", async () => {
    const sent = logged();
    renderApp("/account");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Revoke" }));
    const dialog = screen.getByRole("alertdialog", { name: "Revoke “Lumiverse”?" });
    // the safe choice has the focus, and Escape cancels
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(sent.some((one: Sent) => one.method === "DELETE")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Revoke" }));
    await user.click(screen.getByRole("button", { name: "Revoke “Lumiverse”" }));
    await waitFor(() =>
      expect(screen.getByText("No app tokens yet.")).toBeInTheDocument(),
    );
    const deleted = sent.find((one: Sent) => one.method === "DELETE");
    expect(deleted?.path).toBe("/app-token/ada/5");
  });
});
