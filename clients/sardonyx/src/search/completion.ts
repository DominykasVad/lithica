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
  escaped = true,
): { query: string; cursor: number } {
  const text = (negated ? "-" : "") + (escaped ? escapeValue(tag) : tag);
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

/**
 * In a list of tag names (the tags of an upload, not a query), the name
 * under the cursor: every word is one, written as it is. The prefix is
 * that name as query text, for asking the site.
 */
export function completingName(text: string, cursor: number): Completing | null {
  const token = tokens(text).find((one) => one.start <= cursor && cursor <= one.end);
  return token ? { token, negated: false, prefix: escapeValue(token.text) } : null;
}

/** The list with that name replaced by the tag, as it is named. */
export function takeName(
  text: string,
  { token }: Completing,
  tag: string,
): { query: string; cursor: number } {
  return take(text, { token, negated: false, prefix: "" }, tag, false);
}
