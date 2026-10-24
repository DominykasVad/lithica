/**
 * Logging in and out. The password is sent once, to make a login token
 * (`POST /user-token/<user>`), and not kept: from then on every request is
 * made with the token. The token lives in memory, and is kept for as long
 * as the session is meant to last:
 *
 * - without "remember me", in this tab's sessionStorage: a reload keeps it,
 *   closing the tab ends it, and the site lets the token expire in 24 hours;
 * - with "remember me", in this browser's localStorage, and the token
 *   expires in 90 days.
 *
 * The expiry is the site's, so a token that is left behind (a tab closed
 * without logging out) stops working by itself.
 */
import {
  api,
  authorization,
  basicAuthorization,
  type Credentials,
  setCredentials,
} from "@/api/client";
import { unwrap } from "@/api/errors";

const STORAGE_KEY = "sardonyx.session";

const HOUR = 60 * 60 * 1000;
const SESSION_LIFETIME = 24 * HOUR;
const REMEMBERED_LIFETIME = 90 * 24 * HOUR;

// Storage can be missing or refuse (a private window, blocked site data):
// then the session lasts as long as the page.
function store(kind: "local" | "session"): Storage | null {
  try {
    return kind === "local" ? localStorage : sessionStorage;
  } catch {
    return null;
  }
}

function readStored(kind: "local" | "session"): Credentials | null {
  try {
    const stored = JSON.parse(store(kind)?.getItem(STORAGE_KEY) ?? "null");
    if (
      typeof stored?.user === "string" &&
      typeof stored?.token === "string" &&
      stored.user &&
      stored.token
    ) {
      return { user: stored.user, token: stored.token };
    }
  } catch {
    // nothing usable stored
  }
  return null;
}

function writeStored(kind: "local" | "session", credentials: Credentials): void {
  try {
    store(kind)?.setItem(STORAGE_KEY, JSON.stringify(credentials));
  } catch {
    // not kept; the session lasts as long as the page
  }
}

function clearStored(): void {
  for (const kind of ["local", "session"] as const) {
    try {
      store(kind)?.removeItem(STORAGE_KEY);
    } catch {
      // nothing to clear, or not allowed to
    }
  }
}

/**
 * The session kept from an earlier visit (remembered) or from before a
 * reload of this tab, made the current one.
 */
export function restoreSession(): Credentials | null {
  const stored = readStored("local") ?? readStored("session");
  setCredentials(stored);
  return stored;
}

export async function logIn(
  user: string,
  password: string,
  remember: boolean,
): Promise<Credentials> {
  const created = await unwrap(
    api.POST("/user-token/{user_name}", {
      params: { path: { user_name: user } },
      headers: { Authorization: basicAuthorization(user, password) },
      body: {
        enabled: true,
        note: remember ? "Sardonyx, remembered" : "Sardonyx session",
        expirationTime: new Date(
          Date.now() + (remember ? REMEMBERED_LIFETIME : SESSION_LIFETIME),
        ).toISOString(),
      },
    }),
  );
  if (!created.token) {
    throw new Error("The site made no login token.");
  }
  // the name as the site has it, which may differ in case from what was typed
  const credentials = { user: created.user?.name ?? user, token: created.token };
  setCredentials(credentials);
  clearStored();
  writeStored(remember ? "local" : "session", credentials);
  return credentials;
}

/**
 * Delete the login token on the site, and forget it here. It is forgotten
 * here also when the site cannot be told: the user asked to be logged out.
 * Returns the error of the site, if any, for showing it.
 */
export async function logOut(credentials: Credentials): Promise<unknown> {
  forgetSession();
  try {
    await unwrap(
      api.DELETE("/user-token/{user_name}/{user_token}", {
        params: {
          path: { user_name: credentials.user, user_token: credentials.token },
        },
        // forgotten here already: the token is given to this request itself
        headers: { Authorization: authorization(credentials) },
      }),
    );
    return null;
  } catch (error) {
    return error;
  }
}

/** Forget the session here only: for a token the site no longer takes. */
export function forgetSession(): void {
  setCredentials(null);
  clearStored();
}
