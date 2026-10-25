import { useState } from "react";

/** How the library lists results: pages of 50 or 100, or loading as one scrolls. */
export type PerPage = 50 | 100 | "auto";

export const PER_PAGE_CHOICES: readonly PerPage[] = [50, 100, "auto"];

const STORAGE_KEY = "sardonyx.perPage";
const DEFAULT: PerPage = "auto";

function stored(): PerPage {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "50" || value === "100") {
      return Number(value) as PerPage;
    }
  } catch {
    // storage may be blocked
  }
  return DEFAULT;
}

/** The choice of this browser, kept in localStorage. */
export function usePerPage(): [PerPage, (next: PerPage) => void] {
  const [perPage, setPerPage] = useState<PerPage>(stored);
  const choose = (next: PerPage) => {
    setPerPage(next);
    try {
      if (next === DEFAULT) {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, String(next));
      }
    } catch {
      // not kept; it lasts as long as the page
    }
  };
  return [perPage, choose];
}
