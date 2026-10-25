/**
 * The engine's query text, as far as the client takes it apart: tokens
 * split by whitespace, an optional leading `-` that negates one, and
 * `key:value` for a named token (lithica/search/parser.py).
 */

/** A token of the query text and where it is in it. */
export interface Token {
  text: string;
  start: number;
  end: number;
}

export function tokens(query: string): Token[] {
  return [...query.matchAll(/\S+/g)].map((match) => ({
    text: match[0],
    start: match.index,
    end: match.index + match[0].length,
  }));
}

/** The parts of one token: negation, and the key of a named token. */
export interface Parts {
  negated: boolean;
  /** lower case, unescaped; null for a token without a key */
  key: string | null;
  /** what follows the key's colon, or the whole token, still escaped */
  value: string;
}

export function parts(token: string): Parts {
  const negated = token.startsWith("-");
  const body = negated ? token.slice(1) : token;
  // the first colon that is not escaped ends the key
  const named = body.match(/^(.*?)(?<!\\):(.*)$/s);
  if (!named) {
    return { negated, key: null, value: body };
  }
  return {
    negated,
    key: unescapeValue(named[1] ?? "").toLowerCase(),
    value: named[2] ?? "",
  };
}

/**
 * Text as one value of a token, matched as written. The engine treats as
 * special a backslash, `*` (any text), `:` (a key), `,` (one of several),
 * `..` (a range) and a leading `-` (not); its parser accepts an escape only
 * for `\ * : - . ,` (search/configs/util.py).
 */
export function escapeValue(text: string): string {
  return text
    .replace(/[\\*:,]/g, "\\$&")
    .replace(/\.{2,}/g, (dots) => "\\.".repeat(dots.length))
    .replace(/^-/, "\\-");
}

/** What `escapeValue` made, back as text. */
export function unescapeValue(text: string): string {
  return text.replace(/\\(.)/gs, "$1");
}

/** Split a value at the commas that are not escaped. */
export function values(value: string): string[] {
  return value.split(/(?<!\\),/);
}

/** True when the value holds a range: two dots, neither escaped. */
export function isRange(value: string): boolean {
  return /(?<!\\)\.(?<!\\)\./.test(value);
}

/**
 * The query text with one token replaced by `text`, or for null taken out
 * with the whitespace before it. Everything else stays as typed.
 */
export function replaceToken(query: string, token: Token, text: string | null): string {
  if (text !== null) {
    return query.slice(0, token.start) + text + query.slice(token.end);
  }
  const before = query.slice(0, token.start).replace(/\s+$/, "");
  const after = query.slice(token.end);
  return before ? before + after : after.replace(/^\s+/, "");
}
