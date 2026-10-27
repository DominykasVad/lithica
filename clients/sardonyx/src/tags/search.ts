import { escapeValue, parts, tokens } from "@/search/query";

/**
 * Where the tags page is, in its URL: `q`, the query in the engine's tag
 * syntax; `category`, the one category shown (none: all); `at`, the
 * offset of the first tag shown.
 */
export interface TagsSearch {
  q?: string;
  category?: string;
  at?: number;
}

export function validateTagsSearch(search: Record<string, unknown>): TagsSearch {
  const text = (value: unknown) =>
    typeof value === "string" && value.trim() ? value : undefined;
  const at = Number(search.at);
  return {
    q: text(search.q),
    category: text(search.category),
    at: Number.isSafeInteger(at) && at > 0 ? at : undefined,
  };
}

/** The search for this query, category and offset, with the defaults left out. */
export function tagsSearch(
  q: string,
  category: string | undefined,
  at = 0,
): TagsSearch {
  return {
    q: q.trim() || undefined,
    category: category || undefined,
    at: at > 0 ? at : undefined,
  };
}

/**
 * What the site is asked: the query as typed, the category as a token of
 * its own, and the most used first unless the query sorts otherwise.
 */
export function tagQuery(q: string, category: string | undefined): string {
  const sorted = tokens(q).some((token) => parts(token.text).key === "sort");
  return [
    q.trim(),
    category ? `category:${escapeValue(category)}` : "",
    sorted ? "" : "sort:usages",
  ]
    .filter(Boolean)
    .join(" ");
}
