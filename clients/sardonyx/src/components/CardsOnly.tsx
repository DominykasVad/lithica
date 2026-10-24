import type { ReactNode } from "react";
import { useHasCards } from "@/app/info";

/** What is about character cards: shown only on a site with the cards module. */
export function CardsOnly({ children }: { children: ReactNode }) {
  return useHasCards() ? children : null;
}
