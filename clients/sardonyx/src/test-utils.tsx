/**
 * Helpers for the tests: a stand-in for the site's API, and the app
 * rendered whole at a path.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { StrictMode } from "react";
import { vi } from "vitest";
import { NsfwProvider } from "./app/nsfw";
import { ThemeProvider } from "./app/theme";
import { AuthProvider } from "./auth/AuthProvider";
import { makeRouter } from "./router";

export interface Sent {
  method: string;
  path: string;
  authorization: string | null;
  body: unknown;
  /** let go of by the app (StrictMode's second mount asks anew) */
  readonly aborted: boolean;
}

type Answer = {
  status?: number;
  body: unknown;
  /** more headers; JSON's Content-Type unless `raw` */
  headers?: Record<string, string>;
  /** the body as these bytes, not as JSON (a file) */
  raw?: Uint8Array<ArrayBuffer>;
};
// an answer can take its time: a promise is waited for
type Handler = (sent: Sent) => Answer | Promise<Answer>;

/**
 * The site, as far as a test needs it: answers by "METHOD /path" (the path
 * without /api), and remembers every request. What it has no answer for is
 * a 404 in the API's form.
 */
export function fakeSite(routes: Record<string, Answer | Handler>) {
  const sent: Sent[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const url = new URL(request.url);
    const text = await request.text();
    const one: Sent = {
      method: request.method,
      path: url.pathname.replace(/^\/api/, "") + url.search,
      authorization: request.headers.get("Authorization"),
      body: text ? JSON.parse(text) : undefined,
      get aborted() {
        return request.signal.aborted;
      },
    };
    sent.push(one);
    const route =
      routes[`${one.method} ${one.path}`] ??
      routes[`${one.method} ${url.pathname.replace(/^\/api/, "")}`];
    const answer =
      typeof route === "function"
        ? await route(one)
        : (route ?? {
            status: 404,
            body: {
              name: "NotFound",
              title: "Not found",
              description: `No ${one.path}.`,
            },
          });
    if (answer.raw) {
      return new Response(answer.raw, {
        status: answer.status ?? 200,
        headers: { "Content-Type": "application/octet-stream", ...answer.headers },
      });
    }
    return new Response(JSON.stringify(answer.body), {
      status: answer.status ?? 200,
      headers: { "Content-Type": "application/json", ...answer.headers },
    });
  });
  return sent;
}

export const INFO = {
  postCount: 67,
  diskUsage: null,
  serverTime: "2026-10-24T09:00:00Z",
  modules: ["cards"],
  config: { name: "My cards", privileges: {} },
};

/** The whole app, at a path, as a fresh page load would start it. */
export function renderApp(path = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = makeRouter(createMemoryHistory({ initialEntries: [path] }));
  // as main.tsx renders it: StrictMode runs every effect twice
  const view = render(
    <StrictMode>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <NsfwProvider>
              <RouterProvider router={router} />
            </NsfwProvider>
          </AuthProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </StrictMode>,
  );
  return { ...view, router, queryClient };
}
