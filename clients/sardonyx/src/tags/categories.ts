import type { components } from "@/api/schema";

export type TagCategory = components["schemas"]["TagCategory"];

/** A colour the site set for a category, if it is one a style can take. */
export function swatch(color: string | undefined): string | null {
  if (!color || color === "default") {
    return null;
  }
  return /^(#[0-9a-f]{3,8}|[a-z]+)$/i.test(color) ? color : null;
}

/** The categories in the site's order. */
export function inOrder(categories: readonly TagCategory[] | undefined): TagCategory[] {
  return [...(categories ?? [])].sort((x, y) => (x.order ?? 0) - (y.order ?? 0));
}

/** The category the cards module files a card's creator under. */
export const CREATOR_CATEGORY = "creator";
// the colour it is created with: the creator chips of the design reference
export const CREATOR_COLOR = "#7e2f22";

export function hasCategory(
  categories: readonly TagCategory[] | undefined,
  name: string,
): boolean {
  return (categories ?? []).some(
    (category) => category.name?.toLowerCase() === name.toLowerCase(),
  );
}
