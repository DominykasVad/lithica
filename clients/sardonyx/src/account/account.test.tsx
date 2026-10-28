import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { authorization } from "@/api/client";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

const TOKEN = "f5a2c0de-0000-4000-8000-000000000001";
const RESET = "0123456789abcdef0123456789abcdef";

const withMail = (mail: boolean, extra: Record<string, unknown> = {}) => ({
  ...INFO,
  config: { ...INFO.config, canSendMails: mail, passwordRegex: "^.{5,}$" },
  ...extra,
});

function site(routes: Record<string, unknown> = {}, mail = true) {
  return fakeSite({
    "GET /info": { body: withMail(mail) },
    "GET /posts": { body: { total: 0, results: [] } },
    ...routes,
  } as never);
}

describe("starting a password reset", () => {
  it("is offered on the login form of a site that can send mail", async () => {
    site();
    const view = renderApp("/login");
    await userEvent
      .setup()
      .click(await screen.findByRole("link", { name: "Forgot your password?" }));
    await waitFor(() =>
      expect(view.router.state.location.pathname).toBe("/password-reset"),
    );
  });

  it("is not offered where the site cannot send mail, and says why there", async () => {
    site({}, false);
    renderApp("/login");
    await screen.findByLabelText("User name");
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Forgot your password?" })).toBeNull(),
    );
    renderApp("/password-reset");
    expect(await screen.findByText(/This site cannot send mail/)).toBeInTheDocument();
    expect(screen.queryByLabelText("User name or email")).toBeNull();
  });

  async function ask(who: string) {
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("User name or email"), who);
    await user.click(screen.getByRole("button", { name: "Send me a link" }));
  }

  const SENT =
    /If that account has an email, a link to reset its password is on its way/;

  it("asks the site, and says the same whatever the site answers", async () => {
    for (const answer of [
      { body: {} },
      {
        status: 404,
        body: { name: "UserNotFoundError", title: "x", description: "x" },
      },
      { status: 400, body: { name: "ValidationError", title: "x", description: "x" } },
    ]) {
      const sent = site({ "GET /password-reset/ada@example.com": answer });
      const view = renderApp("/password-reset");
      await ask("ada@example.com");
      expect(await screen.findByRole("status")).toHaveTextContent(SENT);
      expect(sent.map((one: Sent) => one.path)).toContain(
        "/password-reset/ada%40example.com",
      );
      view.unmount();
    }
  });

  it("says plainly when the site cannot send mail after all", async () => {
    site({
      "GET /password-reset/ada": {
        status: 500,
        body: {
          name: "MailNotConfiguredError",
          title: "Server configuration error",
          description: "No mail.",
        },
      },
    });
    renderApp("/password-reset");
    await ask("ada");
    expect(await screen.findByText(/This site cannot send mail/)).toBeInTheDocument();
    expect(screen.queryByText(SENT)).toBeNull();
  });

  it("can be reached on a site that shows nothing without logging in", async () => {
    fakeSite({
      "GET /info": { body: withMail(true, { visibility: "login" }) },
    } as never);
    const view = renderApp("/password-reset");
    expect(await screen.findByLabelText("User name or email")).toBeInTheDocument();
    expect(view.router.state.location.pathname).toBe("/password-reset");
  });
});

describe("the link of the mail", () => {
  it("takes the token off the address, then resets on a click and shows the password once", async () => {
    const sent = site({
      "POST /password-reset/ada%3Alace": { body: { password: "n3w-Pass-word" } },
    });
    const view = renderApp(`/password-reset/ada:lace:${RESET}`);
    await waitFor(() =>
      expect(view.router.state.location.pathname).toBe("/password-reset/confirm"),
    );
    // the history entry of the link is replaced: no address holds the token
    expect(view.router.history.length).toBe(1);
    expect(view.router.state.location.href).not.toContain(RESET);
    expect(screen.getByText("ada:lace")).toBeInTheDocument();
    // nothing is asked before the click
    expect(sent.some((one: Sent) => one.method === "POST")).toBe(false);

    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    await user.click(screen.getByRole("button", { name: "Reset the password" }));
    const password = await screen.findByLabelText("New password");
    expect(password).toHaveValue("n3w-Pass-word");
    // split at the last ':': the name may hold one, the token does not
    const post = sent.find((one: Sent) => one.method === "POST");
    expect(post?.path).toBe("/password-reset/ada%3Alace");
    expect(post?.body).toEqual({ token: RESET });
    await user.click(screen.getByRole("button", { name: "Copy the password" }));
    expect(writeText).toHaveBeenCalledWith("n3w-Pass-word");
    expect(
      screen.getByRole("link", { name: "Log in and change it now" }),
    ).toHaveAttribute("href", "/login?redirect=%2Faccount");
  });

  it("shows the site's refusal of a used or expired token", async () => {
    site({
      "POST /password-reset/ada": {
        status: 400,
        body: {
          name: "InvalidPasswordResetTokenError",
          title: "Invalid token",
          description: "The link has expired.",
        },
      },
    });
    renderApp(`/password-reset/ada:${RESET}`);
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Reset the password" }));
    expect(await screen.findByText("The link has expired.")).toBeInTheDocument();
  });

  it("says so for a link without a token, and for the confirm page opened by itself", async () => {
    site();
    const first = renderApp("/password-reset/ada");
    expect(await screen.findByText(/This link is not complete/)).toBeInTheDocument();
    first.unmount();
    renderApp("/password-reset/confirm");
    expect(await screen.findByText(/This link is not complete/)).toBeInTheDocument();
  });
});

describe("the account page", () => {
  function logged(routes: Record<string, unknown> = {}) {
    sessionStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: TOKEN }),
    );
    return site({
      "GET /user/ada": (one: Sent) =>
        one.authorization === `Basic ${btoa("ada:old-pass")}`
          ? { body: { name: "ada", version: 7, rank: "regular" } }
          : one.authorization?.startsWith("Basic ")
            ? {
                status: 403,
                body: {
                  name: "AuthError",
                  title: "x",
                  description: "Invalid password.",
                },
              }
            : { body: { name: "ada", version: 7, rank: "regular" } },
      "PUT /user/ada": { body: { name: "ada", version: 8 } },
      ...routes,
    });
  }

  async function change(current: string, next: string) {
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Current password"), current);
    await user.type(screen.getByLabelText("New password"), next);
    await user.click(screen.getByRole("button", { name: "Change the password" }));
  }

  it("is in the user menu", async () => {
    logged();
    const view = renderApp("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "ada" }));
    await user.click(await screen.findByRole("menuitem", { name: "Account" }));
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/account"));
  });

  it("checks the current password, then sends the new one with the version", async () => {
    const sent = logged();
    renderApp("/account");
    await change("old-pass", "brand-new");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your password is changed.",
    );
    const put = sent.find((one: Sent) => one.method === "PUT");
    expect(put?.body).toEqual({ version: 7, password: "brand-new" });
    expect(put?.authorization).toBe(authorization({ user: "ada", token: TOKEN }));
    // the passwords are not left in the page
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.getByLabelText("New password")).toHaveValue("");
  });

  it("changes nothing with a wrong current password, and keeps the session", async () => {
    const sent = logged();
    renderApp("/account");
    await change("wrong-pass", "brand-new");
    expect(
      await screen.findByText("The current password is wrong"),
    ).toBeInTheDocument();
    expect(sent.some((one: Sent) => one.method === "PUT")).toBe(false);
    expect(
      within(screen.getByRole("banner")).getByRole("button", { name: "ada" }),
    ).toBeInTheDocument();
  });

  it("holds the new password to the site's rule before asking", async () => {
    const sent = logged();
    renderApp("/account");
    await change("old-pass", "abc");
    expect(await screen.findByText(/must match \^\.\{5,\}\$/)).toBeInTheDocument();
    // neither the current password checked nor anything changed
    expect(sent.some((one: Sent) => one.authorization?.startsWith("Basic "))).toBe(
      false,
    );
    expect(sent.some((one: Sent) => one.method === "PUT")).toBe(false);
  });

  it("asks a visitor to log in", async () => {
    site();
    renderApp("/account");
    expect(await screen.findByRole("link", { name: "Log in" })).toBeInTheDocument();
  });
});
