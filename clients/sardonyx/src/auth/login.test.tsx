import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { authorization } from "@/api/client";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

const TOKEN = "f5a2c0de-0000-4000-8000-000000000001";
const ADA_TOKEN = authorization({ user: "ada", token: TOKEN });

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
    await logIn(false);

    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/"));
    const login = sent.find((one) => one.method === "POST");
    expect(login?.path).toBe("/user-token/ada");
    expect(login?.body).toEqual({ enabled: true, note: "Sardonyx" });
    // the password went in that one request and nowhere else
    const withPassword = sent.filter((one) => one.authorization?.startsWith("Basic"));
    expect(withPassword).toHaveLength(1);
    const after = sent.slice(sent.indexOf(login as Sent) + 1);
    expect(after.length).toBeGreaterThan(0);
    for (const one of after) {
      expect(one.authorization).toBe(ADA_TOKEN);
    }
    // not remembered: nothing in storage, and the password in no field
    expect(localStorage.length).toBe(0);
    expect(document.body.innerHTML).not.toContain("secret!");
  });

  it("with remember me, keeps the token for the next visit", async () => {
    site();
    const first = renderApp("/");
    await logIn(true);
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("sardonyx.session") ?? "null")).toEqual({
      user: "ada",
      token: TOKEN,
    });
    expect(localStorage.getItem("sardonyx.session")).not.toContain("secret!");
    first.unmount();

    // a reload: the app starts again from what is stored
    const sent = site();
    renderApp("/");
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(sent.length).toBeGreaterThan(0));
    expect(sent.every((one) => one.authorization === ADA_TOKEN)).toBe(true);
  });

  it("without remember me, a reload is logged out", async () => {
    site();
    const first = renderApp("/");
    await logIn(false);
    expect(
      await (await header()).findByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
    first.unmount();
    // what is in memory goes with the page
    const { setCredentials } = await import("@/api/client");
    setCredentials(null);

    const sent = site();
    renderApp("/");
    expect(
      await (await header()).findByRole("link", { name: "Log in" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(sent.length).toBeGreaterThan(0));
    expect(sent.every((one) => one.authorization === null)).toBe(true);
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
    localStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: TOKEN }),
    );
  }

  it("deletes the token on the site and here", async () => {
    await loggedInAndRemembered();
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
                name: "AuthError",
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
