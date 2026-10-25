import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import type { components } from "@/api/schema";

export type Post = components["schemas"]["Post"];

/** The API's largest page: what auto load asks for at a time. */
export const BATCH = 100;

/** Only what a tile shows: its card summary only where there are cards. */
export function tileFields(hasCards: boolean): string {
  return ["id", "type", "thumbnailUrl", ...(hasCards ? ["card"] : [])].join(",");
}

export function fetchPosts(
  query: string,
  offset: number,
  limit: number,
  fields: string,
  signal?: AbortSignal,
) {
  return unwrap(
    api.GET("/posts", {
      params: { query: { query, offset, limit, fields } },
      signal,
    }),
  );
}
