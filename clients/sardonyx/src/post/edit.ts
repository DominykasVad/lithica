/**
 * Editing a post: which of its fields this user may change, what an edit
 * changes (only that is sent), and the post's new state in what the app
 * has kept of it.
 */
import type { QueryClient } from "@tanstack/react-query";
import type { Post } from "./queries";

/** The fields of the editor, each under the privilege that changes it. */
export const EDIT_PRIVILEGES = {
  tags: "posts:edit:tags",
  safety: "posts:edit:safety",
  source: "posts:edit:source",
} as const;

export type EditField = keyof typeof EDIT_PRIVILEGES;
export const EDIT_FIELDS = Object.keys(EDIT_PRIVILEGES) as EditField[];

export const DELETE_PRIVILEGE = "posts:delete";

export type Safety = "safe" | "sketchy" | "unsafe";

/** What the editor holds: the tags as text, one name after another. */
export interface Draft {
  tags: string;
  safety: Safety;
  source: string;
}

/** The fields of the editor this user may change, in the editor's order. */
export function editableFields(can: ((name: string) => boolean) | null): EditField[] {
  return can ? EDIT_FIELDS.filter((field) => can(EDIT_PRIVILEGES[field])) : [];
}

/** "tags, safety and source": the fields, for a button's label. */
export function listed(fields: readonly string[]): string {
  if (fields.length <= 1) {
    return fields.join("");
  }
  return `${fields.slice(0, -1).join(", ")} and ${fields.at(-1)}`;
}

export function tagNames(post: Post): string[] {
  return (post.tags ?? []).map((tag) => tag.names?.[0] ?? "").filter(Boolean);
}

/** The names in a field of tags: words, each once (the site's names ignore case). */
export function parseTags(text: string): string[] {
  const names = text.split(/\s+/).filter(Boolean);
  return names.filter(
    (name, i) =>
      names.findIndex((other) => other.toLowerCase() === name.toLowerCase()) === i,
  );
}

export function draftOf(post: Post): Draft {
  return {
    tags: tagNames(post).join(" "),
    safety: (post.safety as Safety | undefined) ?? "safe",
    source: post.source ?? "",
  };
}

function sameTags(left: string[], right: string[]): boolean {
  const key = (names: string[]) =>
    names
      .map((name) => name.toLowerCase())
      .sort()
      .join(" ");
  return key(left) === key(right);
}

/**
 * What the edit changes of the post, among the fields this user may
 * change: only that goes into the request, with the version edited.
 */
export function changes(
  post: Post,
  draft: Draft,
  fields: readonly EditField[],
): { tags?: string[]; safety?: Safety; source?: string } {
  const changed: { tags?: string[]; safety?: Safety; source?: string } = {};
  if (fields.includes("tags") && !sameTags(parseTags(draft.tags), tagNames(post))) {
    changed.tags = parseTags(draft.tags);
  }
  if (fields.includes("safety") && draft.safety !== (post.safety ?? "safe")) {
    changed.safety = draft.safety;
  }
  if (fields.includes("source") && draft.source !== (post.source ?? "")) {
    changed.source = draft.source;
  }
  return changed;
}

interface PostList {
  total?: number;
  results?: Post[];
}

function isPostList(data: unknown): data is PostList {
  return (
    typeof data === "object" &&
    data !== null &&
    Array.isArray((data as PostList).results)
  );
}

/**
 * The post as the site now has it, wherever the app keeps it: the post
 * page's queries take it whole; a list (the library's pages and batches)
 * takes the fields it holds of it. The lists are marked stale too: a
 * search the post has left, or joined, is asked again when it is next
 * shown.
 */
export function savedPost(client: QueryClient, post: Post): void {
  client.setQueriesData<Post>({ queryKey: ["post", post.id] }, (old) =>
    old && !Array.isArray(old) && "id" in old && old.id === post.id
      ? { ...old, ...post }
      : old,
  );
  client.setQueriesData<unknown>({ queryKey: ["posts"] }, (old: unknown) =>
    isPostList(old)
      ? {
          ...old,
          results: old.results?.map((one) =>
            one.id === post.id
              ? {
                  ...one,
                  ...Object.fromEntries(
                    Object.entries(post).filter(([key]) => key in one),
                  ),
                }
              : one,
          ),
        }
      : old,
  );
  client.invalidateQueries({ queryKey: ["posts"] });
}

/** A deleted post out of what the app keeps: its page, and every list. */
export function deletedPost(client: QueryClient, id: number): void {
  client.removeQueries({ queryKey: ["post", id] });
  client.removeQueries({ queryKey: ["card", id] });
  client.setQueriesData<unknown>({ queryKey: ["posts"] }, (old: unknown) =>
    isPostList(old)
      ? {
          ...old,
          total: old.total !== undefined ? Math.max(0, old.total - 1) : old.total,
          results: old.results?.filter((one) => one.id !== id),
        }
      : old,
  );
  client.invalidateQueries({ queryKey: ["posts"] });
}
