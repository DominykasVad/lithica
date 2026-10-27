import { queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import type { components } from "@/api/schema";

export type Post = components["schemas"]["Post"];
export type Card = components["schemas"]["Card"];
export type LorebookEntry = components["schemas"]["LorebookEntry"];

/** What the post page shows of a post: its card summary only where there are cards. */
export function postFields(hasCards: boolean): string {
  return [
    "id",
    // what an edit or a delete is made on
    "version",
    "type",
    "mimeType",
    "safety",
    "source",
    "fileSize",
    "canvasWidth",
    "canvasHeight",
    "contentUrl",
    "thumbnailUrl",
    "tags",
    "user",
    "creationTime",
    "lastEditTime",
    ...(hasCards ? ["card"] : []),
  ].join(",");
}

export function postQuery(id: number, fields: string) {
  return queryOptions({
    queryKey: ["post", id, fields],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/post/{post_id}", {
          params: { path: { post_id: String(id) }, query: { fields } },
          signal,
        }),
      ),
  });
}

/** The posts before and after this one in the search it was opened from. */
export function aroundQuery(id: number, q: string) {
  return queryOptions({
    queryKey: ["post", id, "around", q],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/post/{post_id}/around", {
          params: { path: { post_id: String(id) }, query: { query: q, fields: "id" } },
          signal,
        }),
      ),
  });
}

/** The site's tag categories, in their order. */
export const categoriesQuery = queryOptions({
  queryKey: ["tag-categories"],
  queryFn: ({ signal }) => unwrap(api.GET("/tag-categories", { signal })),
  staleTime: 5 * 60 * 1000,
});

/** The whole card of a post: one request per post, kept while it is looked at. */
export function cardQuery(id: number) {
  return queryOptions({
    queryKey: ["card", id],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/modules/cards/post/{post_id}", {
          params: { path: { post_id: String(id) } },
          signal,
        }),
      ),
    // a card does not change while it is read; the lorebook page uses it too
    staleTime: 5 * 60 * 1000,
  });
}
