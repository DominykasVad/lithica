import { type LibrarySearch, validateLibrarySearch } from "@/library/search";

/**
 * Where a post page is: the library's search and place it was opened
 * from (`q`, `at`: the way back, and what previous and next go through),
 * and the card viewer's tab.
 */
export interface PostSearch extends LibrarySearch {
  tab?: string;
}

export function validatePostSearch(search: Record<string, unknown>): PostSearch {
  const tab = typeof search.tab === "string" && search.tab ? search.tab : undefined;
  return { ...validateLibrarySearch(search), tab };
}

/** The kinds of lorebook entries the lorebook page shows. */
export const KINDS = ["all", "constant", "selective", "disabled"] as const;
export type Kind = (typeof KINDS)[number];

/** The lorebook page: the way back, and its filter text and kind. */
export interface LorebookSearch extends LibrarySearch {
  filter?: string;
  kind?: Exclude<Kind, "all">;
}

export function validateLorebookSearch(
  search: Record<string, unknown>,
): LorebookSearch {
  const filter =
    typeof search.filter === "string" && search.filter ? search.filter : undefined;
  const kind = KINDS.find((one) => one !== "all" && one === search.kind) as
    | LorebookSearch["kind"]
    | undefined;
  return { ...validateLibrarySearch(search), filter, kind };
}

/** The library's part of a search: where "back" goes. */
export function fromLibrary({ q, at }: LibrarySearch): LibrarySearch {
  return { q, at };
}
