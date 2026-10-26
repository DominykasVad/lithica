import { Link } from "@tanstack/react-router";
import type { TileLayout } from "./layout";
import type { Post } from "./posts";
import type { LibrarySearch } from "./search";

// The thumbnail's URL as the API gives it, which may be relative to the
// site: it is resolved against where the app is, never against the page.
const SITE = new URL(import.meta.env.BASE_URL, document.baseURI);

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function cardFacts(card: NonNullable<Post["card"]>): string {
  return [
    card.greetingCount == null
      ? null
      : plural(card.greetingCount, "greeting", "greetings"),
    card.lorebookEntryCount == null ? null : `lorebook ${card.lorebookEntryCount}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * One post in the library: its thumbnail, and its card when it has one.
 * Its link carries the search and the place in it, for the post page's
 * way back and its previous and next.
 */
export function PostTile({
  post,
  layout,
  from,
}: {
  post: Post;
  layout: TileLayout;
  from: LibrarySearch;
}) {
  const { card } = post;
  const badge = (card?.format ?? post.type ?? "").toUpperCase();
  return (
    <Link
      to="/posts/$id"
      params={{ id: String(post.id) }}
      search={from}
      className="group flex flex-col gap-2 rounded-xl text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
      style={{ width: layout.tileWidth, height: layout.tileHeight }}
    >
      <div
        className="relative overflow-hidden rounded-xl border bg-muted"
        style={{ width: layout.tileWidth, height: layout.pictureHeight }}
      >
        {post.thumbnailUrl ? (
          <img
            src={new URL(post.thumbnailUrl, SITE).href}
            alt=""
            width={layout.tileWidth}
            height={layout.pictureHeight}
            loading="lazy"
            className="size-full object-cover"
          />
        ) : null}
        {badge ? (
          <span className="absolute top-2 left-2 rounded-md bg-card px-2 py-0.5 font-semibold text-[11px] text-muted-foreground">
            {badge}
          </span>
        ) : null}
      </div>
      <div className="flex h-16 min-w-0 flex-col">
        {card ? (
          <>
            <span className="truncate font-semibold font-serif text-lg leading-tight group-hover:text-primary">
              {card.name || "Unnamed card"}
            </span>
            {card.creator ? (
              <span className="truncate text-muted-foreground text-sm">
                by {card.creator}
              </span>
            ) : null}
            <span className="truncate text-muted-foreground text-xs">
              {cardFacts(card)}
            </span>
          </>
        ) : (
          <span className="text-muted-foreground text-sm">Post {post.id}</span>
        )}
      </div>
    </Link>
  );
}

/** Where a tile will be, while it loads: the same size, nothing in it. */
export function TilePlaceholder({ layout }: { layout: TileLayout }) {
  return (
    <div
      aria-hidden
      data-placeholder
      className="flex flex-col gap-2"
      style={{ width: layout.tileWidth, height: layout.tileHeight }}
    >
      <div
        className="animate-pulse rounded-xl bg-muted"
        style={{ height: layout.pictureHeight }}
      />
      <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
    </div>
  );
}
