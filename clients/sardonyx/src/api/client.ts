/**
 * The client of the Lithica API. Every request and response is typed from
 * the API's contract (`schema.ts`, generated from doc/openapi.json by
 * `pnpm api:generate`; never edit it by hand).
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

/** A user and a login token of theirs: what a request is made as. */
export interface Credentials {
  user: string;
  token: string;
}

// The credentials of this browser tab, in memory. Whether they are also
// kept across visits is the session's business (src/auth/session.ts).
let credentials: Credentials | null = null;
let sessionEnded: () => void = () => {};

export function setCredentials(next: Credentials | null): void {
  credentials = next;
}

export function getCredentials(): Credentials | null {
  return credentials;
}

/**
 * What to do when the API refuses the token the app sent: it was deleted,
 * disabled or has expired, here or on another device.
 */
export function onSessionEnded(listener: () => void): void {
  sessionEnded = listener;
}

/** `Token <base64 of user:token>`, the API's token authentication. */
export function authorization({ user, token }: Credentials): string {
  return `Token ${base64(`${user}:${token}`)}`;
}

/** `Basic <base64 of user:password>`, for the one request that logs in. */
export function basicAuthorization(user: string, password: string): string {
  return `Basic ${base64(`${user}:${password}`)}`;
}

function base64(value: string): string {
  // of the UTF-8 bytes: btoa alone takes Latin-1 only
  const bytes = new TextEncoder().encode(value);
  return btoa(String.fromCharCode(...bytes));
}

// The server's answer to a token it does not take (deleted, disabled,
// expired, or of a user who is gone). A missing privilege is an AuthError,
// with the same status, and leaves the session alone.
const INVALID_TOKEN_ERROR = "InvalidTokenError";

const headers: Middleware = {
  onRequest({ request }) {
    // the API answers only a request that says it accepts JSON
    request.headers.set("Accept", "application/json");
    // a request that brings its own (the login) keeps them
    if (credentials && !request.headers.has("Authorization")) {
      request.headers.set("Authorization", authorization(credentials));
    }
    return request;
  },
  async onResponse({ request, response }) {
    if (
      response.status !== 403 ||
      !request.headers.get("Authorization")?.startsWith("Token ")
    ) {
      return response;
    }
    const body: unknown = await response
      .clone()
      .json()
      .catch(() => null);
    if (
      typeof body === "object" &&
      body !== null &&
      "name" in body &&
      body.name === INVALID_TOKEN_ERROR
    ) {
      sessionEnded();
    }
    return response;
  },
};

/**
 * Where the API is: `api/` beside the app, as the client's image and the
 * dev server serve it. Made absolute against the page, as a request needs.
 */
export const API_BASE_URL = new URL(`${import.meta.env.BASE_URL}api`, document.baseURI)
  .href;

export function createApiClient(baseUrl: string = API_BASE_URL) {
  const client = createClient<paths>({
    baseUrl,
    // looked up at each request, not once: what fetch is can change (tests)
    fetch: (request) => globalThis.fetch(request),
  });
  client.use(headers);
  return client;
}

export const api = createApiClient();
