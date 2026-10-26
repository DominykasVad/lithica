import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  type RouterHistory,
} from "@tanstack/react-router";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Home } from "./app/Home";
import { Login } from "./app/Login";
import { NotFound, Shell } from "./app/Shell";
import { Library } from "./library/Library";
import { validateLibrarySearch } from "./library/search";
import { validateLorebookSearch, validatePostSearch } from "./post/search";

const rootRoute = createRootRoute({
  component: Shell,
  notFoundComponent: NotFound,
  // what a page throws is shown as any failure is, not as a blank page
  errorComponent: ({ error }) => (
    <main className="mx-auto max-w-5xl p-6">
      <ApiErrorMessage error={error} />
    </main>
  ),
});

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: Home,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  // where to go once logged in: a path of this app, checked where it is used
  validateSearch: (search: Record<string, unknown>): { redirect?: string } =>
    typeof search.redirect === "string" ? { redirect: search.redirect } : {},
  component: function LoginPage() {
    const { redirect } = loginRoute.useSearch();
    return <Login redirect={redirect} />;
  },
});

export const libraryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/posts",
  validateSearch: validateLibrarySearch,
  component: Library,
});

export const postRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/posts/$id",
  validateSearch: validatePostSearch,
  // the post and lorebook pages bring the Markdown renderer: loaded when
  // first opened, not with the app
  component: lazyRouteComponent(() => import("./post/PostPage"), "PostPage"),
});

export const lorebookRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/posts/$id/lorebook",
  validateSearch: validateLorebookSearch,
  component: lazyRouteComponent(() => import("./card/LorebookPage"), "LorebookPage"),
});

export const routeTree = rootRoute.addChildren([
  homeRoute,
  loginRoute,
  libraryRoute,
  postRoute,
  lorebookRoute,
]);

// The search part of a URL as plain `key=value` pairs: `?q=coastal&at=100`.
// The router's default would read `q=123` as a number and write strings
// that look like JSON in quotes.
function parseSearch(search: string): Record<string, unknown> {
  return Object.fromEntries(new URLSearchParams(search));
}

function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value !== undefined && value !== null) {
      params.set(key, String(value));
    }
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function makeRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    basepath: import.meta.env.BASE_URL,
    parseSearch,
    stringifySearch,
    // back to a page goes back to where it was scrolled to
    scrollRestoration: true,
  });
}

export const router = makeRouter();

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
