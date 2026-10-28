import { type RefObject, useEffect, useState } from "react";

/**
 * The size of a tile. It is fixed for a breakpoint, so that the rows of
 * auto load have a height known before anything is drawn.
 */
export const GAP = 20;
// below the picture: a card's name, creator and facts, or a post's number
const CARD_TEXT_HEIGHT = 64;
const PLAIN_TEXT_HEIGHT = 20;
const TEXT_GAP = 8;

/** What a tile's caption holds: a card's three lines, or one line. */
export type Captions = "card" | "plain";

export interface TileLayout {
  tileWidth: number;
  pictureHeight: number;
  /** the text below the picture */
  textHeight: number;
  /** the picture and the text below it */
  tileHeight: number;
  columns: number;
}

/** The layout with captions of this kind: a row of posts without cards is lower. */
export function withCaptions(layout: TileLayout, captions: Captions): TileLayout {
  const textHeight = captions === "card" ? CARD_TEXT_HEIGHT : PLAIN_TEXT_HEIGHT;
  return {
    ...layout,
    textHeight,
    tileHeight: layout.pictureHeight + TEXT_GAP + textHeight,
  };
}

function layoutFor(width: number, viewport: number): TileLayout {
  const tileWidth = viewport >= 640 ? 180 : 150;
  const pictureHeight = (tileWidth * 4) / 3;
  return withCaptions(
    {
      tileWidth,
      pictureHeight,
      textHeight: 0,
      tileHeight: 0,
      columns: Math.max(1, Math.floor((width + GAP) / (tileWidth + GAP))),
    },
    "card",
  );
}

/** The tile layout for the width of an element, kept up to date. */
export function useTileLayout(element: RefObject<HTMLElement | null>): TileLayout {
  // before it is laid out (and in tests) the window's width stands in
  const measure = () =>
    layoutFor(element.current?.clientWidth || window.innerWidth, window.innerWidth);
  const [layout, setLayout] = useState<TileLayout>(measure);

  // biome-ignore lint/correctness/useExhaustiveDependencies: measure reads the ref
  useEffect(() => {
    const update = () =>
      setLayout((current) => {
        const next = measure();
        return next.columns === current.columns && next.tileWidth === current.tileWidth
          ? current
          : next;
      });
    update();
    const observer = new ResizeObserver(update);
    if (element.current) {
      observer.observe(element.current);
    }
    window.addEventListener("resize", update);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [element]);
  return layout;
}
