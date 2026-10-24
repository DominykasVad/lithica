/**
 * Helpers for the tests: a stand-in for the site's API, and the app
 * rendered whole at a path.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { ThemeProvider } from "./app/theme";
import { AuthProvider } from "./auth/AuthProvider";
import { routeTree } from "./router";

export interface Sent {
  method: string;
  path: string;
  authorization: string | null;
  body: unknown;
}

type Answer = { status?: number; body: unknown };
type Handler = (sent: Sent) => Answer;

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
    };
    sent.push(one);
    const route =
      routes[`${one.method} ${one.path}`] ??
      routes[`${one.method} ${url.pathname.replace(/^\/api/, "")}`];
    const answer =
      typeof route === "function"
        ? route(one)
        : (route ?? {
            status: 404,
            body: {
              name: "NotFound",
              title: "Not found",
              description: `No ${one.path}.`,
            },
          });
    return new Response(JSON.stringify(answer.body), {
      status: answer.status ?? 200,
      headers: { "Content-Type": "application/json" },
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
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  const view = render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { ...view, router, queryClient };
}
