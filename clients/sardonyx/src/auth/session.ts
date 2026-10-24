/**
 * Logging in and out. The password is sent once, to make a login token
 * (`POST /user-token/<user>`), and not kept: from then on every request is
 * made with the token. The token lives in memory; with "remember me" it is
 * also written to this browser's localStorage, to be found on the next
 * visit.
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

// Storage can be missing or refuse (a private window, blocked site data):
// then the session lasts as long as the tab.
function readStored(): Credentials | null {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
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

function writeStored(credentials: Credentials | null): void {
  try {
    if (credentials) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(credentials));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // not kept; the session lasts as long as the tab
  }
}

/** The session remembered from an earlier visit, made the current one. */
export function restoreSession(): Credentials | null {
  const stored = readStored();
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
      body: { enabled: true, note: "Sardonyx" },
    }),
  );
  if (!created.token) {
    throw new Error("The site made no login token.");
  }
  // the name as the site has it, which may differ in case from what was typed
  const credentials = { user: created.user?.name ?? user, token: created.token };
  setCredentials(credentials);
  writeStored(remember ? credentials : null);
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
  writeStored(null);
}
