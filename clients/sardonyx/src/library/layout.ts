import { type RefObject, useEffect, useState } from "react";

/**
 * The size of a tile. It is fixed for a breakpoint, so that the rows of
 * auto load have a height known before anything is drawn.
 */
export const GAP = 20;
// the name, the creator and the facts below the picture
const TEXT_HEIGHT = 64;
const TEXT_GAP = 8;

export interface TileLayout {
  tileWidth: number;
  pictureHeight: number;
  /** the picture and the text below it */
  tileHeight: number;
  columns: number;
}

function layoutFor(width: number, viewport: number): TileLayout {
  const tileWidth = viewport >= 640 ? 180 : 150;
  const pictureHeight = (tileWidth * 4) / 3;
  return {
    tileWidth,
    pictureHeight,
    tileHeight: pictureHeight + TEXT_GAP + TEXT_HEIGHT,
    columns: Math.max(1, Math.floor((width + GAP) / (tileWidth + GAP))),
  };
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
