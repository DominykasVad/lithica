/**
 * The card filters of the library, read from and written into the query
 * text: the text is the truth, the panel one way of editing it. Each
 * control owns the `card-*` tokens of its key (also with `-min` or `-max`,
 * which the engine reads as a range of the same key) and nothing else.
 *
 * A control shows what it can write itself. Any other token of its key
 * (negated, a range, several of them) stays in the text untouched, and the
 * control says "custom" until it is changed.
 */
import {
  escapeValue,
  isRange,
  parts,
  replaceToken,
  type Token,
  tokens,
  unescapeValue,
  values,
} from "./query";

export const SPECS = ["v1", "v2", "v3"] as const;
export const FORMATS = ["png", "charx"] as const;
export type Spec = (typeof SPECS)[number];
export type Format = (typeof FORMATS)[number];
export type Lorebook = "yes" | "no";

export interface FilterValues {
  creator: string;
  spec: Spec[];
  format: Format[];
  lorebook: Lorebook;
  greetings: number;
}

export type FilterName = keyof FilterValues;

export type Control<T> =
  | { state: "none" }
  | { state: "set"; value: T }
  | { state: "custom" };

export type Filters = { [Name in FilterName]: Control<FilterValues[Name]> };

const KEYS: Record<FilterName, string> = {
  creator: "card-creator",
  spec: "card-spec",
  format: "card-format",
  lorebook: "card-lorebook",
  greetings: "card-greetings",
};

const NONE = { state: "none" } as const;
const CUSTOM = { state: "custom" } as const;

function owns(name: FilterName, token: Token): boolean {
  const { key } = parts(token.text);
  const base = KEYS[name];
  return key === base || key === `${base}-min` || key === `${base}-max`;
}

/** The words of a list token, if each is one of `known`, without repeats. */
function words<T extends string>(value: string, known: readonly T[]): T[] | null {
  const listed = values(value).map((one) => unescapeValue(one).toLowerCase());
  if (!listed.every((one) => (known as readonly string[]).includes(one))) {
    return null;
  }
  return known.filter((one) => listed.includes(one));
}

const READ: { [Name in FilterName]: (value: string) => FilterValues[Name] | null } = {
  creator(value) {
    // words joined by `*` (what the panel writes for spaces), no wildcard
    // at either end, no list and no range
    if (!value || /(?<!\\),/.test(value) || isRange(value)) {
      return null;
    }
    const pieces = value.split(/(?<!\\)\*/);
    if (pieces.some((piece) => !piece)) {
      return null;
    }
    return pieces.map(unescapeValue).join(" ");
  },
  spec: (value) => words(value, SPECS),
  format: (value) => words(value, FORMATS),
  lorebook(value) {
    const word = unescapeValue(value).toLowerCase();
    if (["yes", "true", "1"].includes(word)) {
      return "yes";
    }
    return ["no", "false", "0"].includes(word) ? "no" : null;
  },
  greetings(value) {
    const atLeast = value.match(/^(\d+)\.\.$/);
    return atLeast ? Number(atLeast[1]) : null;
  },
};

function read<Name extends FilterName>(
  name: Name,
  owned: Token[],
): Control<FilterValues[Name]> {
  if (owned.length === 0) {
    return NONE;
  }
  const [only] = owned;
  if (owned.length > 1 || !only) {
    return CUSTOM;
  }
  const { negated, key, value } = parts(only.text);
  const shown = !negated && key === KEYS[name] ? READ[name](value) : null;
  return shown === null ? CUSTOM : { state: "set", value: shown };
}

/** What the panel shows for this query text. */
export function readFilters(query: string): Filters {
  const all = tokens(query);
  const of = (name: FilterName) => all.filter((token) => owns(name, token));
  return {
    creator: read("creator", of("creator")),
    spec: read("spec", of("spec")),
    format: read("format", of("format")),
    lorebook: read("lorebook", of("lorebook")),
    greetings: read("greetings", of("greetings")),
  };
}

/** How many of the controls filter (custom ones too): what "Filters (2)" counts. */
export function countFilters(query: string): number {
  return Object.values(readFilters(query)).filter((control) => control.state !== "none")
    .length;
}

const WRITE: { [Name in FilterName]: (value: FilterValues[Name]) => string | null } = {
  creator(value) {
    // a space cannot be in a token: the words are joined by a wildcard
    const pieces = value.trim().split(/\s+/).filter(Boolean);
    return pieces.length ? pieces.map(escapeValue).join("*") : null;
  },
  // every one or none of them is no filter at all
  spec: (value) =>
    value.length === 0 || value.length === SPECS.length ? null : value.join(","),
  format: (value) =>
    value.length === 0 || value.length === FORMATS.length ? null : value.join(","),
  lorebook: (value) => value,
  greetings: (value) => (value >= 1 ? `${Math.floor(value)}..` : null),
};

/**
 * The query text with one filter set to `value`, or taken out for null:
 * the control's tokens are replaced where the first of them was (or the
 * new one is added at the end), and every other token stays as typed.
 */
export function writeFilter<Name extends FilterName>(
  query: string,
  name: Name,
  value: FilterValues[Name] | null,
): string {
  const written = value === null ? null : WRITE[name](value);
  const token = written === null ? null : `${KEYS[name]}:${written}`;
  const owned = tokens(query).filter((one) => owns(name, one));
  const [first] = owned;
  if (!first) {
    return token === null ? query : [query.trimEnd(), token].filter(Boolean).join(" ");
  }
  // from the end, so that the places of the earlier ones stay right
  let result = query;
  for (const one of owned.slice(1).reverse()) {
    result = replaceToken(result, one, null);
  }
  return replaceToken(result, first, token);
}
