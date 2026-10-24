import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Home } from "./app/Home";
import { Login } from "./app/Login";
import { NotFound, Shell } from "./app/Shell";

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

export const routeTree = rootRoute.addChildren([homeRoute, loginRoute]);

export function makeRouter() {
  return createRouter({ routeTree, basepath: import.meta.env.BASE_URL });
}

export const router = makeRouter();

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
