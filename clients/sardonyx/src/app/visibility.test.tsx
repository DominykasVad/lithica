import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

const TOKEN = "f5a2c0de-0000-4000-8000-000000000001";

/** A site of this visibility; ada logs in with "secret!". */
function site(visibility: string) {
  return fakeSite({
    "GET /info": { body: { ...INFO, modules: [], visibility, nsfwTag: "nsfw" } },
    "GET /posts": { body: { query: "", offset: 0, limit: 100, total: 0, results: [] } },
    "POST /user-token/ada": (sent: Sent) =>
      sent.authorization === `Basic ${btoa("ada:secret!")}`
        ? { body: { user: { name: "ada" }, token: TOKEN, version: 1 } }
        : { status: 403, body: { name: "AuthError", title: "No", description: "No." } },
  } as never);
}

// what the app asked of the site, but GET /info
const asked = (sent: Sent[]) =>
  sent.filter((one) => !one.path.startsWith("/info")).map((one) => one.path);

describe("a site that shows nothing without logging in", () => {
  it("sends a visitor to the login page, asking nothing else of the site", async () => {
    const sent = site("login");
    const view = renderApp("/posts?q=sea");
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/login"));
    expect(await screen.findByLabelText("User name")).toBeInTheDocument();
    expect(asked(sent)).toEqual([]);
    // no navigation to pages the visitor cannot see, nor a second way in
    const banner = within(screen.getByRole("banner"));
    expect(banner.queryByRole("navigation", { name: "Main" })).toBeNull();
    expect(banner.queryByRole("link", { name: "Log in" })).toBeNull();
    expect(banner.getByRole("link", { name: "Sardonyx" })).toBeInTheDocument();
  });

  it("sends every page there, and back to it once logged in", async () => {
    site("login");
    const view = renderApp("/posts?q=sea");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("User name"), "ada");
    await user.type(screen.getByLabelText("Password"), "secret!");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/posts"));
    expect(view.router.state.location.search).toEqual({ q: "sea" });
    expect(
      within(screen.getByRole("banner")).getByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
  });

  it("sends a page that is not there to the login page too", async () => {
    site("login");
    const view = renderApp("/nowhere");
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/login"));
    expect(screen.queryByRole("heading", { name: "Not found" })).toBeNull();
  });

  it("shows a logged-in user every page", async () => {
    sessionStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: TOKEN }),
    );
    const sent = site("login");
    const view = renderApp("/posts");
    await waitFor(() =>
      expect(asked(sent)).toContainEqual(expect.stringMatching(/^\/posts\?/)),
    );
    expect(view.router.state.location.pathname).toBe("/posts");
  });

  it("sends the visitor back to the login page on logging out", async () => {
    sessionStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: TOKEN }),
    );
    fakeSite({
      "GET /info": { body: { ...INFO, modules: [], visibility: "login" } },
      "GET /posts": { body: { total: 0, results: [] } },
      [`DELETE /user-token/ada/${TOKEN}`]: { body: {} },
    } as never);
    const view = renderApp("/posts");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "ada" }));
    await user.click(await screen.findByRole("menuitem", { name: "Log out" }));
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/login"));
  });
});

describe("other sites", () => {
  for (const visibility of ["open", "nsfw-login", undefined]) {
    it(`show their pages without logging in (${visibility ?? "not said"})`, async () => {
      const sent = site(visibility as string);
      const view = renderApp("/posts");
      await waitFor(() =>
        expect(asked(sent)).toContainEqual(expect.stringMatching(/^\/posts\?/)),
      );
      expect(view.router.state.location.pathname).toBe("/posts");
      expect(
        within(screen.getByRole("banner")).getByRole("link", { name: "Log in" }),
      ).toBeInTheDocument();
    });
  }

  it("are not taken for closed ones when GET /info fails, nor asked over and over", async () => {
    const sent = fakeSite({
      "GET /info": {
        status: 503,
        body: { name: "HttpError", title: "Busy", description: "" },
      },
      "GET /posts": { body: { total: 0, results: [] } },
    } as never);
    const view = renderApp("/posts");
    await waitFor(() => expect(screen.getByRole("search")).toBeInTheDocument());
    expect(view.router.state.location.pathname).toBe("/posts");
    // the page asks again once as it comes (StrictMode: twice), and stops
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(sent.filter((one) => one.path === "/info").length).toBeLessThanOrEqual(4);
  });
});
