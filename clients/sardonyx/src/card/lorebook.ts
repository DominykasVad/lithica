/**
 * What the lorebook views show of an entry, and how they sort entries
 * into kinds and find them by text.
 */

import type { LorebookEntry } from "@/post/queries";
import type { Kind } from "@/post/search";

/** An entry with its place in the lorebook (its index), which keys it. */
export interface Numbered {
  index: number;
  entry: LorebookEntry;
}

/** The entry's name, else its comment, else its first key. */
export function entryTitle({ index, entry }: Numbered): string {
  return (
    entry.name?.trim() ||
    entry.comment?.trim() ||
    entry.keys?.find((key) => key.trim())?.trim() ||
    `Entry ${index + 1}`
  );
}

export type Mode = "always active" | "selective" | "keyword";

/**
 * How the entry is triggered: always (constant), by its keys and its
 * secondary keys (selective: only with secondary keys, which is what the
 * flag is about), or by its keys.
 */
export function modeOf(entry: LorebookEntry): Mode {
  if (entry.constant) {
    return "always active";
  }
  return entry.selective && (entry.secondaryKeys?.length ?? 0) > 0
    ? "selective"
    : "keyword";
}

/** Off in the card: the chat program leaves it out. */
export function isDisabled(entry: LorebookEntry): boolean {
  return entry.enabled === false;
}

export function isKind(entry: LorebookEntry, kind: Kind): boolean {
  switch (kind) {
    case "all":
      return true;
    case "constant":
      return modeOf(entry) === "always active";
    case "selective":
      return modeOf(entry) === "selective";
    case "disabled":
      return isDisabled(entry);
  }
}

/** The text the filter looks in, lower case: keys, name, comment, content. */
export function searchText(entry: LorebookEntry): string {
  return [
    ...(entry.keys ?? []),
    ...(entry.secondaryKeys ?? []),
    entry.name ?? "",
    entry.comment ?? "",
    entry.content ?? "",
  ]
    .join("\n")
    .toLowerCase();
}

export interface Counts {
  entries: number;
  constant: number;
  disabled: number;
  characters: number;
}

export function countsOf(entries: readonly LorebookEntry[]): Counts {
  return {
    entries: entries.length,
    constant: entries.filter((entry) => modeOf(entry) === "always active").length,
    disabled: entries.filter(isDisabled).length,
    characters: entries.reduce((sum, entry) => sum + (entry.content?.length ?? 0), 0),
  };
}

/** The details of an entry that the card sets, as label and value. */
export function detailsOf(entry: LorebookEntry): [string, string][] {
  const yesNo = (value: boolean) => (value ? "yes" : "no");
  const details: [string, string | null][] = [
    ["Order", entry.order == null ? null : String(entry.order)],
    ["Position", entry.position || null],
    ["Priority", entry.priority == null ? null : String(entry.priority)],
    ["Case sensitive", entry.caseSensitive == null ? null : yesNo(entry.caseSensitive)],
    ["Regex", entry.useRegex == null ? null : yesNo(entry.useRegex)],
    [
      "Secondary keys",
      entry.secondaryKeys?.length ? entry.secondaryKeys.join(", ") : null,
    ],
    ["Id", entry.id == null || entry.id === "" ? null : String(entry.id)],
  ];
  return details.filter((one): one is [string, string] => one[1] !== null);
}

const NUMBER = new Intl.NumberFormat("en");

export function formatNumber(value: number): string {
  return NUMBER.format(value);
}
