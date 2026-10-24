import { queryOptions, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";

/** `GET /info`: the site, and the modules it has switched on. */
export const infoQuery = queryOptions({
  queryKey: ["info"],
  queryFn: () => unwrap(api.GET("/info")),
  // what a site offers changes with a restart, not while one looks at it
  staleTime: 5 * 60 * 1000,
});

/**
 * The modules the site has switched on, as `GET /info` lists them; empty
 * until it has answered. The app offers a module's features only when the
 * module is listed: what a site has is learnt from the site, not built in.
 */
export function useModules(): string[] {
  const info = useQuery(infoQuery);
  return info.data?.modules ?? [];
}

export function useHasCards(): boolean {
  return useModules().includes("cards");
}
