import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import { useAuth } from "@/auth/AuthProvider";
import { infoQuery } from "./info";

/** The ranks of the site, lowest first: a privilege names the lowest that has it. */
export const RANKS = [
  "anonymous",
  "restricted",
  "regular",
  "power",
  "moderator",
  "administrator",
  "nobody",
] as const;

/** Whether a user of `rank` has the privilege, by the site's table (GET /info). */
export function hasPrivilege(
  privileges: Record<string, unknown> | undefined,
  name: string,
  rank: string,
): boolean {
  const needed = privileges?.[name];
  const at = RANKS.indexOf(rank as (typeof RANKS)[number]);
  const least = RANKS.indexOf(needed as (typeof RANKS)[number]);
  return at >= 0 && least >= 0 && at >= least;
}

/** The rank of who is using the app: "anonymous" when nobody is logged in; null until known. */
export function useRank(): string | null {
  const { user } = useAuth();
  const account = useQuery({
    queryKey: ["user", user, "rank"],
    enabled: user !== null,
    staleTime: 5 * 60 * 1000,
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/user/{user_name}", {
          params: { path: { user_name: user ?? "" }, query: { fields: "rank" } },
          signal,
        }),
      ),
  });
  if (user === null) {
    return "anonymous";
  }
  return account.data?.rank ?? null;
}

/**
 * What this user may do, by the site's privilege table: `can(name)` for a
 * privilege; null while the site or the rank is not known. Only what the
 * user can do is offered; the site still decides each request.
 */
export function usePrivileges(): ((name: string) => boolean) | null {
  const info = useQuery(infoQuery);
  const rank = useRank();
  if (!info.data || rank === null) {
    return null;
  }
  const privileges = info.data.config?.privileges;
  return (name) => hasPrivilege(privileges, name, rank);
}

/** What uploading takes: putting a file up, and making a post of it. */
export const UPLOAD_PRIVILEGES = ["uploads:create", "posts:create:identified"] as const;

/** Whether this user may upload: null while the site or the rank is not known. */
export function useCanUpload(): boolean | null {
  const can = usePrivileges();
  return can ? UPLOAD_PRIVILEGES.every(can) : null;
}

/** The lowest rank that has all these privileges here, for saying so. */
export function lowestRank(
  privileges: Record<string, unknown> | undefined,
  names: readonly string[],
): string | null {
  const ranks = names.map((name) => RANKS.indexOf(privileges?.[name] as never));
  const highest = Math.max(...ranks);
  return highest >= 0 ? (RANKS[highest] ?? null) : null;
}

/** The lowest rank that may upload here, for saying so. */
export function uploadRank(
  privileges: Record<string, unknown> | undefined,
): string | null {
  return lowestRank(privileges, UPLOAD_PRIVILEGES);
}
