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

// The credentials of this browser tab, in memory only. Keeping them across
// visits ("remember me") is the login's business, not the client's.
let credentials: Credentials | null = null;

export function setCredentials(next: Credentials | null): void {
  credentials = next;
}

export function getCredentials(): Credentials | null {
  return credentials;
}

/** `Token <base64 of user:token>`, the API's token authentication. */
export function authorization({ user, token }: Credentials): string {
  // base64 of the UTF-8 bytes: btoa alone takes Latin-1 only
  const bytes = new TextEncoder().encode(`${user}:${token}`);
  return `Token ${btoa(String.fromCharCode(...bytes))}`;
}

const headers: Middleware = {
  onRequest({ request }) {
    // the API answers only a request that says it accepts JSON
    request.headers.set("Accept", "application/json");
    if (credentials) {
      request.headers.set("Authorization", authorization(credentials));
    }
    return request;
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
