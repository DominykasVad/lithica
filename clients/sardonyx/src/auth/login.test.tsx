import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { authorization } from "@/api/client";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

const TOKEN = "f5a2c0de-0000-4000-8000-000000000001";
const ADA_TOKEN = authorization({ user: "ada", token: TOKEN });
const SESSION = JSON.stringify({ user: "ada", token: TOKEN });
const HOUR = 60 * 60 * 1000;

// The expiry the login asked for, as hours from when it was sent.
function hoursAsked(login: Sent | undefined, sentAt: number): number {
  const body = login?.body as { expirationTime?: string } | undefined;
  const expires = Date.parse(body?.expirationTime ?? "");
  expect(body?.expirationTime).toMatch(/Z$/);
  return Math.round((expires - sentAt) / HOUR);
}

// A reload of the tab: what is in memory goes, sessionStorage stays.
async function reload(view: { unmount: () => void }) {
  view.unmount();
  const { setCredentials } = await import("@/api/client");
  setCredentials(null);
}

function site(extra: Record<string, unknown> = {}) {
  return fakeSite({
    "GET /info": { body: INFO },
    "GET /posts": { body: { total: 5, results: [] } },
    "POST /user-token/ada": (sent: Sent) =>
      sent.authorization === `Basic ${btoa("ada:secret!")}`
        ? { body: { user: { name: "ada" }, token: TOKEN, version: 1 } }
        : {
            status: 403,
            body: {
              name: "AuthError",
              title: "Authentication error",
              description: "Invalid password.",
            },
          },
    [`DELETE /user-token/ada/${TOKEN}`]: { body: {} },
    ...extra,
  } as never);
}

async function logIn(remember: boolean) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("link", { name: "Log in" }));
  await user.type(await screen.findByLabelText("User name"), "ada");
  await user.type(screen.getByLabelText("Password"), "secret!");
  if (remember) {
    await user.click(screen.getByLabelText("Remember me on this browser"));
  }
  await user.click(screen.getByRole("button", { name: "Log in" }));
  return user;
}

// the page is drawn once the router has started: wait for it
async function header() {
  return within(await screen.findByRole("banner"));
}

describe("logging in", () => {
  it("makes a login token with the password once, then uses the token", async () => {
    const sent = site();
    const view = renderApp("/");
    const startedAt = Date.now();
    await logIn(false);

    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/"));
    const login = sent.find((one) => one.method === "POST");
    expect(login?.path).toBe("/user-token/ada");
    expect(login?.body).toMatchObject({ enabled: true, note: "Sardonyx session" });
    expect(hoursAsked(login, startedAt)).toBe(24);
    // the password went in that one request and nowhere else
    const withPassword = sent.filter((one) => one.authorization?.startsWith("Basic"));
    expect(withPassword).toHaveLength(1);
    const after = sent.slice(sent.indexOf(login as Sent) + 1);
    expect(after.length).toBeGreaterThan(0);
    for (const one of after) {
      expect(one.authorization).toBe(ADA_TOKEN);
    }
    // not remembered: kept for this tab only, and the password in no field
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.getItem("sardonyx.session")).toBe(SESSION);
    expect(sessionStorage.getItem("sardonyx.session")).not.toContain("secret!");
    expect(document.body.innerHTML).not.toContain("secret!");
  });

  it("with remember me, keeps the token for the next visit", async () => {
    const asked = site();
    const first = renderApp("/");
    const startedAt = Date.now();
    await logIn(true);
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("sardonyx.session") ?? "null")).toEqual({
      user: "ada",
      token: TOKEN,
    });
    expect(localStorage.getItem("sardonyx.session")).not.toContain("secret!");
    expect(sessionStorage.length).toBe(0);
    const login = asked.find((one) => one.method === "POST");
    expect(login?.body).toMatchObject({ enabled: true, note: "Sardonyx, remembered" });
    expect(hoursAsked(login, startedAt)).toBe(90 * 24);
    await reload(first);
    // a new tab has none of this tab's sessionStorage, and still knows the user
    sessionStorage.clear();

    // the app starts again from what is stored
    const sent = site();
    renderApp("/");
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(sent.length).toBeGreaterThan(0));
    expect(sent.every((one) => one.authorization === ADA_TOKEN)).toBe(true);
  });

  it("without remember me, a reload keeps the session", async () => {
    site();
    const first = renderApp("/");
    await logIn(false);
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    await reload(first);

    const sent = site();
    renderApp("/");
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(sent.length).toBeGreaterThan(0));
    expect(sent.every((one) => one.authorization === ADA_TOKEN)).toBe(true);
  });

  it("without remember me, a new tab is logged out", async () => {
    site();
    const first = renderApp("/");
    await logIn(false);
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    await reload(first);
    // a new tab starts with a sessionStorage of its own
    sessionStorage.clear();

    const sent = site();
    renderApp("/");
    expect(
      await (await header()).findByRole("link", { name: "Log in" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(sent.length).toBeGreaterThan(0));
    expect(sent.every((one) => one.authorization === null)).toBe(true);
  });

  it("still logs in when the browser refuses storage, for this page only", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    const sent = site();
    renderApp("/");
    await logIn(true);
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(sent.at(-1)?.authorization).toBe(ADA_TOKEN));
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("shows the site's refusal readably and keeps nobody logged in", async () => {
    site();
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("User name"), "ada");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Authentication error");
    expect(alert).toHaveTextContent("Invalid password.");
    expect((await header()).getByRole("link", { name: "Log in" })).toBeInTheDocument();
    // the password field is emptied
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("goes back where it was sent from, but only within the app", async () => {
    site();
    const view = renderApp("/login?redirect=%2Fsomewhere");
    await logInHere();
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/somewhere"));
  });

  it("does not follow a redirect to another site", async () => {
    site();
    const view = renderApp("/login?redirect=%2F%2Fevil.example%2F");
    await logInHere();
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/"));
  });
});

async function logInHere() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("User name"), "ada");
  await user.type(screen.getByLabelText("Password"), "secret!");
  await user.click(screen.getByRole("button", { name: "Log in" }));
}

describe("logging out", () => {
  async function loggedInAndRemembered() {
    localStorage.setItem("sardonyx.session", SESSION);
  }

  it("deletes the token on the site and here", async () => {
    await loggedInAndRemembered();
    // and a session of this tab, from before remember me was chosen
    sessionStorage.setItem("sardonyx.session", SESSION);
    const sent = site();
    renderApp("/");
    const user = userEvent.setup();
    await user.click(await (await header()).findByRole("button", { name: "ada" }));
    await user.click(await screen.findByRole("menuitem", { name: "Log out" }));

    expect(
      await (await header()).findByRole("link", { name: "Log in" }),
    ).toBeInTheDocument();
    const deleted = sent.find((one) => one.method === "DELETE");
    expect(deleted?.path).toBe(`/user-token/ada/${TOKEN}`);
    expect(deleted?.authorization).toBe(ADA_TOKEN);
    expect(localStorage.getItem("sardonyx.session")).toBeNull();
    expect(sessionStorage.getItem("sardonyx.session")).toBeNull();
    // and asks the site anew, as nobody
    await waitFor(() => expect(sent.at(-1)?.authorization).toBeNull());
  });

  it("logs out here even when the site cannot be told, and says so", async () => {
    await loggedInAndRemembered();
    site({
      [`DELETE /user-token/ada/${TOKEN}`]: {
        status: 503,
        body: {
          name: "HttpError",
          title: "Service unavailable",
          description: "Down for a bit.",
        },
      },
    });
    renderApp("/");
    const user = userEvent.setup();
    await user.click(await (await header()).findByRole("button", { name: "ada" }));
    await user.click(await screen.findByRole("menuitem", { name: "Log out" }));

    expect(
      await (await header()).findByRole("link", { name: "Log in" }),
    ).toBeInTheDocument();
    expect(localStorage.getItem("sardonyx.session")).toBeNull();
    expect(await screen.findByRole("alert")).toHaveTextContent("Down for a bit.");
  });

  it("happens by itself when the site no longer takes the token", async () => {
    await loggedInAndRemembered();
    site({
      "GET /info": (sent: Sent) =>
        sent.authorization
          ? {
              status: 403,
              body: {
                name: "InvalidTokenError",
                title: "Authentication error",
                description: "Invalid token.",
              },
            }
          : { body: INFO },
    });
    renderApp("/");
    expect(await screen.findByText("You are logged out")).toBeInTheDocument();
    expect((await header()).getByRole("link", { name: "Log in" })).toBeInTheDocument();
    expect(localStorage.getItem("sardonyx.session")).toBeNull();
    // and the page is asked for again, as nobody, and shown
    expect(
      await screen.findByRole("heading", { name: "My cards" }),
    ).toBeInTheDocument();
  });

  it("goes by the error's name, not its text", async () => {
    await loggedInAndRemembered();
    site({
      "GET /posts": {
        status: 403,
        body: {
          name: "AuthError",
          title: "Authentication error",
          description: "Invalid token.",
        },
      },
    });
    renderApp("/");
    expect(await screen.findByText("Invalid token.")).toBeInTheDocument();
    expect((await header()).getByRole("button", { name: "ada" })).toBeInTheDocument();
    expect(localStorage.getItem("sardonyx.session")).not.toBeNull();
  });

  it("does not happen for a refusal of another kind", async () => {
    await loggedInAndRemembered();
    site({
      "GET /posts": {
        status: 403,
        body: {
          name: "AuthError",
          title: "Authentication error",
          description: "Insufficient privileges to do this.",
        },
      },
    });
    renderApp("/");
    expect(
      await screen.findByText("Insufficient privileges to do this."),
    ).toBeInTheDocument();
    expect((await header()).getByRole("button", { name: "ada" })).toBeInTheDocument();
    expect(localStorage.getItem("sardonyx.session")).not.toBeNull();
  });
});
