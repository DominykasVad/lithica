/**
 * Where the library is, in its URL: `q`, the query text (none: every
 * post), and `at`, the offset of the first result shown (none: 0). The URL
 * is the same in both list modes, so a link opens the same results however
 * the one who opens it lists them.
 */
export interface LibrarySearch {
  q?: string;
  at?: number;
}

export function validateLibrarySearch(search: Record<string, unknown>): LibrarySearch {
  const q = typeof search.q === "string" && search.q.trim() ? search.q : undefined;
  const at = Number(search.at);
  return {
    q,
    // anything but a whole number above 0 is the start
    at: Number.isSafeInteger(at) && at > 0 ? at : undefined,
  };
}

/** The search for this query text and offset, with the defaults left out. */
export function librarySearch(q: string, at = 0): LibrarySearch {
  return { q: q.trim() || undefined, at: at > 0 ? at : undefined };
}
