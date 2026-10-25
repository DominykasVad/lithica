/**
 * Tag completion in the query text: which token the cursor is in, and the
 * text once a tag is taken for it.
 */
import { escapeValue, parts, replaceToken, type Token, tokens } from "./query";

export interface Completing {
  token: Token;
  negated: boolean;
  /** what has been typed of the tag, as query text */
  prefix: string;
}

/**
 * The token under the cursor (or just before it), when it is one to
 * complete: a tag, typed, maybe negated. A named token (`sort:id`,
 * `card-spec:v2`) is not a tag and is left alone.
 */
export function completing(query: string, cursor: number): Completing | null {
  const token = tokens(query).find((one) => one.start <= cursor && cursor <= one.end);
  if (!token) {
    return null;
  }
  const { negated, key, value } = parts(token.text);
  if (key !== null || !value) {
    return null;
  }
  return { token, negated, prefix: value };
}

/** The engine's query for the tags that start with the prefix, most used first. */
export function suggestionQuery(prefix: string): string {
  return `${prefix}* sort:usages`;
}

/**
 * The query text with the token replaced by the tag (negated if it was),
 * and where the cursor goes: after it, past a space that separates it from
 * what comes next.
 */
export function take(
  query: string,
  { token, negated }: Completing,
  tag: string,
): { query: string; cursor: number } {
  const text = (negated ? "-" : "") + escapeValue(tag);
  const replaced = replaceToken(query, token, text);
  const end = token.start + text.length;
  if (replaced[end] === undefined || !/\s/.test(replaced[end] ?? "")) {
    return {
      query: `${replaced.slice(0, end)} ${replaced.slice(end)}`,
      cursor: end + 1,
    };
  }
  return { query: replaced, cursor: end + 1 };
}
