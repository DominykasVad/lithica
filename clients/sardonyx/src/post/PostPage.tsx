import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Download } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { API_BASE_URL } from "@/api/client";
import { infoQuery, useHasCards } from "@/app/info";
import { CardViewer } from "@/card/CardViewer";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { CardsOnly } from "@/components/CardsOnly";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { LibrarySearch } from "@/library/search";
import { writeFilter } from "@/search/cardFilters";
import { escapeValue } from "@/search/query";
import { isWebUrl } from "@/text/rehype";
import { download, fallbackName } from "./download";
import {
  aroundQuery,
  type Card,
  cardQuery,
  categoriesQuery,
  type Post,
  postFields,
  postQuery,
} from "./queries";
import { fromLibrary } from "./search";

// The URLs of the API, which may be relative to the site: resolved against
// where the app is, never against the page.
const SITE = new URL(import.meta.env.BASE_URL, document.baseURI);
const siteUrl = (url: string) => new URL(url, SITE).href;

const DATE = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) {
    return null;
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : DATE.format(date);
}

export function formatSize(bytes: number): string {
  const units = ["bytes", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return unit === 0
    ? `${bytes} bytes`
    : `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

/**
 * The post's picture at the largest size that fits, a click away from its
 * full size; a video with the browser's controls; a CHARX card (or any
 * other file) as its thumbnail.
 */
function Picture({ post, title }: { post: Post; title: string }) {
  const [full, setFull] = useState(false);
  if (post.type === "video" && post.contentUrl) {
    return (
      // biome-ignore lint/a11y/useMediaCaption: the site has no captions for its videos
      <video
        controls
        preload="metadata"
        src={siteUrl(post.contentUrl)}
        poster={post.thumbnailUrl ? siteUrl(post.thumbnailUrl) : undefined}
        className="max-h-[80vh] w-full rounded-xl bg-muted"
      />
    );
  }
  const isPicture =
    (post.type === "image" || post.type === "animation") && post.contentUrl;
  const source = isPicture ? post.contentUrl : post.thumbnailUrl;
  if (!source) {
    return null;
  }
  const picture = (
    <img
      src={siteUrl(source)}
      alt={title}
      width={isPicture ? (post.canvasWidth ?? undefined) : undefined}
      height={isPicture ? (post.canvasHeight ?? undefined) : undefined}
      className={cn(
        "rounded-xl",
        full ? "max-w-none" : "h-auto max-h-[80vh] w-auto max-w-full object-contain",
      )}
    />
  );
  if (!isPicture) {
    return picture;
  }
  return (
    <div className={cn(full && "overflow-auto")}>
      <button
        type="button"
        aria-label={
          full ? "Fit the picture to the page" : "Show the picture at full size"
        }
        aria-pressed={full}
        onClick={() => setFull((now) => !now)}
        className={cn(
          "block rounded-xl focus-visible:outline-2 focus-visible:outline-ring",
          full ? "cursor-zoom-out" : "cursor-zoom-in",
        )}
      >
        {picture}
      </button>
    </div>
  );
}

/** A colour the site set for a category, if it is one a style can take. */
function swatch(color: string | undefined): string | null {
  if (!color || color === "default") {
    return null;
  }
  return /^(#[0-9a-f]{3,8}|[a-z]+)$/i.test(color) ? color : null;
}

/**
 * The post's tags under their categories, in the categories' order: the
 * one list of tags on the page. The default category has no heading.
 */
function TagGroups({ tags }: { tags: NonNullable<Post["tags"]> }) {
  const categories = useQuery(categoriesQuery);
  // in the categories' order once the site has said it (or could not)
  if (categories.isPending) {
    return null;
  }
  const known = [...(categories.data?.results ?? [])].sort(
    (x, y) => (x.order ?? 0) - (y.order ?? 0),
  );
  const names = [
    ...known.map((category) => category.name ?? ""),
    // a category the site no longer lists, after those it does
    ...new Set(tags.map((tag) => tag.category ?? "")),
  ].filter((name, i, all) => all.indexOf(name) === i);
  const groups = names
    .map((name) => ({
      name,
      color: swatch(known.find((category) => category.name === name)?.color),
      // the site's default, or (when the site did not say) the one named so
      isDefault: categories.data
        ? known.some((category) => category.name === name && category.default)
        : name === "default",
      tags: tags.filter((tag) => (tag.category ?? "") === name && tag.names?.[0]),
    }))
    .filter((group) => group.tags.length > 0);
  if (!groups.length) {
    return <p className="text-muted-foreground text-sm">No tags.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      {groups.map((group) => (
        <section
          key={group.name}
          aria-label={group.isDefault ? "Tags" : `Tags: ${group.name || "no category"}`}
        >
          {group.isDefault ? null : (
            <h3 className="mb-1.5 flex items-center gap-2 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
              {group.color ? (
                <span
                  aria-hidden
                  data-color={group.color}
                  className="size-2.5 rounded-full border"
                  style={{ backgroundColor: group.color }}
                />
              ) : null}
              {group.name || "no category"}
            </h3>
          )}
          <ul className="flex flex-wrap gap-1.5">
            {group.tags.map((tag) => {
              const name = tag.names?.[0] ?? "";
              return (
                <li key={name}>
                  <Link
                    to="/posts"
                    search={{ q: escapeValue(name) }}
                    className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-2.5 py-1 text-secondary-foreground text-sm hover:bg-accent hover:text-accent-foreground"
                    style={
                      group.color
                        ? { boxShadow: `inset 3px 0 0 ${group.color}` }
                        : undefined
                    }
                  >
                    {name}
                    <span className="text-muted-foreground text-xs">{tag.usages}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** Where the post comes from: a link only for a web address. */
function Source({ source }: { source: string }) {
  const lines = source.split(/\r?\n/).filter((line) => line.trim());
  return (
    <ul className="flex flex-col gap-0.5">
      {lines.map((line, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: the lines in order
        <li key={i} className="break-all">
          {isWebUrl(line.trim()) ? (
            <a
              href={line.trim()}
              target="_blank"
              rel="noopener noreferrer nofollow ugc"
              className="text-link underline-offset-4 hover:underline"
            >
              {line.trim()}
            </a>
          ) : (
            line
          )}
        </li>
      ))}
    </ul>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="font-medium">{children}</dd>
    </div>
  );
}

function Facts({ post }: { post: Post }) {
  const created = formatDate(post.creationTime);
  const edited = formatDate(post.lastEditTime);
  return (
    <dl className="grid grid-cols-2 gap-3 rounded-xl border bg-card p-4">
      <Fact label="Safety">{post.safety ?? "unknown"}</Fact>
      {post.fileSize != null ? (
        <Fact label="File size">{formatSize(post.fileSize)}</Fact>
      ) : null}
      {post.canvasWidth && post.canvasHeight ? (
        <Fact label="Dimensions">
          {post.canvasWidth} × {post.canvasHeight}
        </Fact>
      ) : null}
      <Fact label="Uploaded by">{post.user?.name ?? "Anonymous"}</Fact>
      {created ? <Fact label="Uploaded">{created}</Fact> : null}
      {edited ? <Fact label="Last edited">{edited}</Fact> : null}
      {post.source?.trim() ? (
        <div className="col-span-2">
          <Fact label="Source">
            <Source source={post.source} />
          </Fact>
        </div>
      ) : null}
    </dl>
  );
}

// a key typed into a field is the field's; arrows in a tab list are the tabs'
function typingIn(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("[role=tablist], [role=radiogroup], [role=listbox], [role=menu]") !==
      null
  );
}

/** Links to the post before and after in the search, and the arrow keys. */
function PrevNext({ id, from }: { id: number; from: LibrarySearch }) {
  const navigate = useNavigate();
  const around = useQuery(aroundQuery(id, from.q ?? ""));
  const prev = around.data?.prev?.id;
  const next = around.data?.next?.id;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        typingIn(event.target)
      ) {
        return;
      }
      const to =
        event.key === "ArrowLeft"
          ? prev
          : event.key === "ArrowRight"
            ? next
            : undefined;
      if (to !== undefined) {
        event.preventDefault();
        navigate({ to: "/posts/$id", params: { id: String(to) }, search: from });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prev, next, navigate, from]);

  const pill =
    "inline-flex items-center gap-1 rounded-full border border-control-border px-3 py-0.5 text-foreground hover:bg-accent";
  return (
    <span className="ml-auto flex gap-2">
      {prev !== undefined ? (
        <Link
          to="/posts/$id"
          params={{ id: String(prev) }}
          search={from}
          className={pill}
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Previous
        </Link>
      ) : null}
      {next !== undefined ? (
        <Link
          to="/posts/$id"
          params={{ id: String(next) }}
          search={from}
          className={pill}
        >
          Next
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      ) : null}
    </span>
  );
}

function DownloadButton({ post, card }: { post: Post; card: Card | null }) {
  const id = post.id ?? 0;
  const save = useMutation({
    mutationFn: () =>
      card
        ? download(
            `${API_BASE_URL}/modules/cards/post/${id}/download`,
            fallbackName(id, post.contentUrl),
          )
        : download(siteUrl(post.contentUrl ?? ""), fallbackName(id, post.contentUrl)),
  });
  const label = card?.name
    ? `Download ${card.name}.${card.format ?? "png"}`
    : "Download the original";
  return (
    <div className="flex flex-col gap-2">
      <Button
        className="h-11 rounded-xl"
        disabled={save.isPending || (!card && !post.contentUrl)}
        onClick={() => save.mutate()}
      >
        <Download />
        <span className="truncate">{label}</span>
      </Button>
      {save.isError ? <ApiErrorMessage error={save.error} /> : null}
    </div>
  );
}

/**
 * The card's name, creator, version, spec and file. Its tags are not
 * listed here: the module puts them on the post, and the post's tags are
 * the page's one list.
 */
function CardHeader({ card }: { card: Card }) {
  const entries = card.lorebook?.entries?.length ?? 0;
  const greetings =
    (card.firstMessage?.trim() ? 1 : 0) +
    (card.alternateGreetings ?? []).filter((one) => one.trim()).length;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <h1 className="font-semibold font-serif text-4xl leading-tight">
          {card.name || "Unnamed card"}
        </h1>
        <p className="text-sm">
          {card.creator ? (
            <>
              by{" "}
              <Link
                to="/posts"
                search={{ q: writeFilter("", "creator", card.creator) }}
                className="text-link underline-offset-4 hover:underline"
              >
                {card.creator}
              </Link>
            </>
          ) : (
            "Creator unknown"
          )}
          {card.characterVersion ? ` · version ${card.characterVersion}` : null}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-3 rounded-xl border bg-card p-4">
        <Fact label="Spec">{card.spec?.toUpperCase()}</Fact>
        <Fact label="File">{card.format?.toUpperCase()}</Fact>
        <Fact label="Greetings">{greetings}</Fact>
        <Fact label="Lorebook">{entries ? `${entries} entries` : "none"}</Fact>
      </dl>
    </div>
  );
}

/** The card part of a post page: its header and its viewer, once loaded. */
function CardParts({
  post,
  tab,
  onTab,
  from,
}: {
  post: Post;
  tab: string | undefined;
  onTab(tab: string): void;
  from: LibrarySearch;
}) {
  const id = post.id ?? 0;
  const card = useQuery(cardQuery(id));
  if (card.isError) {
    return <ApiErrorMessage error={card.error} />;
  }
  if (!card.data) {
    return <p className="text-muted-foreground">Loading the card…</p>;
  }
  return (
    <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
      <aside className="flex flex-col gap-5 lg:w-[340px] lg:shrink-0">
        <Picture post={post} title={card.data.name || `Post ${id}`} />
        <CardHeader card={card.data} />
        <DownloadButton post={post} card={card.data} />
        <PostDetails post={post} />
      </aside>
      <div className="min-w-0 flex-1">
        <CardViewer
          // another card is another viewer: its pictures start not loaded
          key={id}
          card={card.data}
          postId={id}
          tab={tab}
          onTab={onTab}
          from={from}
        />
      </div>
    </div>
  );
}

function PostDetails({ post }: { post: Post }) {
  return (
    <>
      <Facts post={post} />
      <TagGroups tags={post.tags ?? []} />
    </>
  );
}

function Breadcrumb({
  title,
  id,
  from,
}: {
  title: string;
  id: number | null;
  from: LibrarySearch;
}) {
  return (
    <nav
      aria-label="Breadcrumb"
      className="mb-5 flex flex-wrap items-center gap-2 text-muted-foreground text-sm"
    >
      <Link
        to="/posts"
        search={from}
        className="text-link underline-offset-4 hover:underline"
      >
        Back to library
      </Link>
      <span aria-hidden>/</span>
      <span>{title}</span>
      {id !== null ? <PrevNext id={id} from={from} /> : null}
    </nav>
  );
}

/** `/posts/$id`: a post, and its card on a site with cards. */
export function PostPage() {
  const { id: param } = useParams({ from: "/posts/$id" });
  const search = useSearch({ from: "/posts/$id" });
  const navigate = useNavigate();
  const from = fromLibrary(search);
  const id = Number(param);
  const valid = Number.isSafeInteger(id) && id > 0;
  const info = useQuery(infoQuery);
  const hasCards = useHasCards();
  const known = info.isSuccess || info.isError;
  const post = useQuery({
    ...postQuery(id, postFields(hasCards)),
    enabled: valid && known,
  });

  // the tab is in the URL, without a history entry of its own
  const onTab = (tab: string) =>
    navigate({
      to: "/posts/$id",
      params: { id: param },
      search: { ...search, tab },
      replace: true,
      resetScroll: false,
    });

  if (!valid || post.isError) {
    return (
      <main className="mx-auto flex max-w-5xl flex-col items-start gap-4 px-4 py-6 sm:px-8">
        <Breadcrumb title={`Post ${param}`} id={null} from={from} />
        <h1 className="font-semibold text-2xl">Post {param}</h1>
        <ApiErrorMessage
          error={
            post.error ??
            new Error(`There is no post ${param}: a post's number is a whole number.`)
          }
        />
      </main>
    );
  }
  if (!post.data) {
    return (
      <main className="mx-auto max-w-[1360px] px-4 py-6 sm:px-8">
        <p className="text-muted-foreground">Loading post {id}…</p>
      </main>
    );
  }
  const data = post.data;
  const hasCard = hasCards && data.card != null;
  const title = data.card?.name || `Post ${id}`;
  return (
    <main className="mx-auto max-w-[1360px] px-4 py-6 sm:px-8">
      <Breadcrumb title={title} id={id} from={from} />
      {hasCard ? (
        <CardsOnly>
          <CardParts post={data} tab={search.tab} onTab={onTab} from={from} />
        </CardsOnly>
      ) : (
        <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
          <div className="flex min-w-0 flex-1 justify-center">
            <Picture post={data} title={title} />
          </div>
          <aside className="flex flex-col gap-5 lg:w-80 lg:shrink-0">
            <h1 className="font-semibold font-serif text-3xl">{title}</h1>
            <DownloadButton post={data} card={null} />
            <PostDetails post={data} />
          </aside>
        </div>
      )}
    </main>
  );
}
