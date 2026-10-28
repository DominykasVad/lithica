import { Link } from "@tanstack/react-router";
import {
  BLURRED,
  NSFW_CARD_NAME,
  NsfwCover,
  useNsfwHidden,
  useNsfwNamesHidden,
} from "@/app/nsfw";
import { cn } from "@/lib/utils";
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
 * way back and its previous and next. A NSFW post's thumbnail is blurred
 * unless NSFW is shown; a click on its cover reveals it, and opens nothing.
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
  const { hidden, reveal } = useNsfwHidden(post);
  // on a site that asks for it, the name and creator too, until revealed
  const namesHidden = useNsfwNamesHidden(post);
  const oneLine = layout.textHeight < 64;
  return (
    // the cover is beside the link, over its picture: a button is not put
    // inside a link
    <div className="relative" style={{ width: layout.tileWidth }}>
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
              className={cn("size-full object-cover", hidden && BLURRED)}
            />
          ) : null}
          {badge ? (
            <span className="absolute top-2 left-2 rounded-md bg-card px-2 py-0.5 font-semibold text-[11px] text-muted-foreground">
              {badge}
            </span>
          ) : null}
        </div>
        <div className="flex min-w-0 flex-col" style={{ height: layout.textHeight }}>
          {card && oneLine ? (
            // a card among posts without cards, where the rows have one line
            <span className="truncate font-semibold font-serif leading-tight group-hover:text-primary">
              {namesHidden ? NSFW_CARD_NAME : card.name || "Unnamed card"}
            </span>
          ) : card ? (
            <>
              <span className="truncate font-semibold font-serif text-lg leading-tight group-hover:text-primary">
                {namesHidden ? NSFW_CARD_NAME : card.name || "Unnamed card"}
              </span>
              {card.creator && !namesHidden ? (
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
      {hidden ? (
        <NsfwCover
          compact
          onReveal={reveal}
          className="rounded-xl"
          // as high as the picture, not the whole tile (the height wins over inset-0)
          style={{ height: layout.pictureHeight }}
        />
      ) : null}
    </div>
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
