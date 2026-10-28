import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import {
  type ReactNode,
  useCallback,
  useDeferredValue,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { infoQuery, useHasCards } from "@/app/info";
import {
  HiddenText,
  NSFW_CARD_NAME,
  useNsfwHidden,
  useNsfwNamesHidden,
} from "@/app/nsfw";
import { useDocumentTitle } from "@/app/title";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { cn } from "@/lib/utils";
import { cardQuery, postQuery } from "@/post/queries";
import { fromLibrary, KINDS, type Kind } from "@/post/search";
import { TextModeProvider, TextModeSwitch, useTextMode } from "@/text/CardText";
import { CardImages, ImagesBar } from "@/text/StyledFrame";
import { imageHosts } from "@/text/styled";
import { EntryRow } from "./EntryRow";
import { countsOf, formatNumber, isKind, type Numbered, searchText } from "./lorebook";

// how long typing in the filter rests before the URL says it
const WRITE_MS = 300;
// a closed entry's height, until it is measured
const ROW_ESTIMATE = 58;

const KIND_LABELS: Record<Kind, string> = {
  all: "All",
  constant: "Always active",
  selective: "Selective",
  disabled: "Disabled",
};

interface Indexed extends Numbered {
  text: string;
}

/**
 * A row of the list: measured when it is drawn (and watched, by the
 * list's ResizeObserver), and at once when its entry opens or closes, so
 * the rows below move before the next frame.
 */
function MeasuredRow({
  index,
  measure,
  resize,
  open,
  top,
  children,
}: {
  index: number;
  measure(node: Element | null): void;
  resize(index: number, size: number): void;
  open: boolean;
  top: number;
  children: ReactNode;
}) {
  const row = useRef<HTMLDivElement | null>(null);
  const attach = useCallback(
    (node: HTMLDivElement | null) => {
      row.current = node;
      measure(node);
    },
    [measure],
  );
  // when it opens or closes, not when it is drawn: the list has just
  // measured it then, and a second layout per new row slows scrolling
  const was = useRef(open);
  // biome-ignore lint/correctness/useExhaustiveDependencies: measured anew when it opens or closes
  useLayoutEffect(() => {
    if (was.current !== open && row.current) {
      resize(index, row.current.offsetHeight);
    }
    was.current = open;
  }, [open]);
  return (
    <div
      ref={attach}
      data-index={index}
      className="absolute top-0 left-0 w-full"
      style={{ transform: `translateY(${top}px)` }}
    >
      {children}
    </div>
  );
}

/**
 * `/posts/$id/lorebook`: every entry of a card's lorebook, found by text
 * and by kind (both in the URL), and drawn only where it is on screen, so
 * that thousands of them stay quick.
 */
export function LorebookPage() {
  const { id: param } = useParams({ from: "/posts/$id/lorebook" });
  const search = useSearch({ from: "/posts/$id/lorebook" });
  const navigate = useNavigate();
  const from = fromLibrary(search);
  const id = Number(param);
  const valid = Number.isSafeInteger(id) && id > 0;
  const info = useQuery(infoQuery);
  const hasCards = useHasCards();
  const card = useQuery({ ...cardQuery(id), enabled: valid && hasCards });
  // whether the post is NSFW: its entries are hidden as its card text is
  const post = useQuery({ ...postQuery(id, "id,nsfw"), enabled: valid && hasCards });
  const { hidden, reveal } = useNsfwHidden(post.data);
  const namesHidden = useNsfwNamesHidden(post.data);
  const [mode, setMode] = useTextMode();
  // pictures in Styled only when asked, for this page of this card
  const [images, setImages] = useState(false);

  // what is typed; the list follows it as soon as it can, the URL once
  // typing rests
  const inUrl = search.filter ?? "";
  const [typed, setTyped] = useState(inUrl);
  // the filter this page last wrote into the URL
  const written = useRef<string | null>(null);
  const [seen, setSeen] = useState(inUrl);
  if (inUrl !== seen) {
    setSeen(inUrl);
    if (inUrl !== written.current) {
      // the URL changed elsewhere (back, a link): show what it says
      setTyped(inUrl);
    }
  }
  const filter = useDeferredValue(typed);
  const kind: Kind = search.kind ?? "all";

  useEffect(() => {
    if (typed === inUrl) {
      return;
    }
    const timer = setTimeout(() => {
      written.current = typed;
      navigate({
        to: "/posts/$id/lorebook",
        params: { id: param },
        search: { ...search, filter: typed || undefined },
        replace: true,
        resetScroll: false,
      });
    }, WRITE_MS);
    return () => clearTimeout(timer);
  }, [typed, inUrl, search, navigate, param]);

  const lorebook = card.data?.lorebook;
  const all = useMemo<Indexed[]>(
    () =>
      (lorebook?.entries ?? []).map((entry, index) => ({
        index,
        entry,
        text: searchText(entry),
      })),
    [lorebook],
  );
  const matching = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return needle ? all.filter((one) => one.text.includes(needle)) : all;
  }, [all, filter]);
  const counts = useMemo(
    () =>
      Object.fromEntries(
        KINDS.map((one) => [
          one,
          matching.filter((entry) => isKind(entry.entry, one)).length,
        ]),
      ) as Record<Kind, number>,
    [matching],
  );
  const shown = useMemo(
    () =>
      kind === "all" ? matching : matching.filter((one) => isKind(one.entry, kind)),
    [matching, kind],
  );
  const totals = useMemo(() => countsOf(lorebook?.entries ?? []), [lorebook]);
  const hosts = useMemo(
    () => imageHosts((lorebook?.entries ?? []).map((entry) => entry.content ?? "")),
    [lorebook],
  );

  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());
  const toggle = (index: number) =>
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(index)) {
        next.add(index);
      }
      return next;
    });

  const list = useRef<HTMLDivElement>(null);
  const virtualizer = useWindowVirtualizer({
    count: shown.length,
    estimateSize: () => ROW_ESTIMATE,
    overscan: 6,
    scrollMargin: list.current?.offsetTop ?? 0,
    getItemKey: (i) => shown[i]?.index ?? i,
  });

  const pickKind = (next: Kind) =>
    navigate({
      to: "/posts/$id/lorebook",
      params: { id: param },
      search: { ...search, kind: next === "all" ? undefined : next },
      replace: true,
      resetScroll: false,
    });

  // the name once the post says whether it may be shown: never for a moment before
  const name = !post.data
    ? `Post ${param}`
    : namesHidden
      ? NSFW_CARD_NAME
      : card.data?.name || `Post ${param}`;
  useDocumentTitle(`Lorebook of ${name}`);
  const breadcrumb = (
    <nav
      aria-label="Breadcrumb"
      className="flex flex-wrap gap-2 text-muted-foreground text-sm"
    >
      <Link
        to="/posts"
        search={from}
        className="text-link underline-offset-4 hover:underline"
      >
        Library
      </Link>
      <span aria-hidden>/</span>
      <Link
        to="/posts/$id"
        params={{ id: param }}
        search={from}
        className="text-link underline-offset-4 hover:underline"
      >
        {name}
      </Link>
      <span aria-hidden>/</span>
      <span>Lorebook</span>
    </nav>
  );

  const known = info.isSuccess || info.isError;
  if (known && !hasCards) {
    return (
      <main className="mx-auto flex max-w-[1100px] flex-col gap-5 px-4 py-6 sm:px-8">
        {breadcrumb}
        <p className="text-muted-foreground">
          This site does not show character cards.
        </p>
      </main>
    );
  }
  if (card.isError) {
    return (
      <main className="mx-auto flex max-w-[1100px] flex-col gap-5 px-4 py-6 sm:px-8">
        {breadcrumb}
        <ApiErrorMessage error={card.error} />
      </main>
    );
  }
  if (post.isError) {
    return (
      <main className="mx-auto flex max-w-[1100px] flex-col gap-5 px-4 py-6 sm:px-8">
        {breadcrumb}
        <ApiErrorMessage error={post.error} />
      </main>
    );
  }
  if (!card.data || !post.data) {
    return (
      <main className="mx-auto flex max-w-[1100px] flex-col gap-5 px-4 py-6 sm:px-8">
        {breadcrumb}
        <p className="text-muted-foreground">Loading the lorebook…</p>
      </main>
    );
  }
  if (hidden) {
    return (
      <main className="mx-auto flex max-w-[1100px] flex-col gap-5 px-4 py-6 sm:px-8">
        {breadcrumb}
        <HiddenText onReveal={reveal} />
      </main>
    );
  }

  const facts = [
    `Lorebook of ${name}`,
    `${formatNumber(totals.entries)} entries`,
    `${formatNumber(totals.characters)} characters`,
    lorebook?.scanDepth == null ? null : `scan depth ${lorebook.scanDepth}`,
    lorebook?.tokenBudget == null ? null : `token budget ${lorebook.tokenBudget}`,
  ].filter(Boolean);
  const items = virtualizer.getVirtualItems();
  const scrollMargin = virtualizer.options.scrollMargin;

  return (
    <main className="mx-auto flex max-w-[1100px] flex-col gap-5 px-4 py-6 sm:px-8">
      {breadcrumb}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-semibold font-serif text-4xl leading-tight">
            {lorebook?.name || "Lorebook"}
          </h1>
          <p className="text-muted-foreground">{facts.join(" · ")}</p>
        </div>
        <TextModeSwitch mode={mode} onChange={setMode} />
      </div>
      {lorebook ? (
        <>
          <div className="flex flex-wrap items-center gap-2.5">
            <label htmlFor="lorebook-filter" className="sr-only">
              Filter entries by key, name, comment or content
            </label>
            <input
              id="lorebook-filter"
              type="search"
              placeholder="Filter by key or content"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              className="h-11 min-w-0 flex-[1_1_320px] rounded-xl border border-control-border bg-card px-3.5 text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            {/* biome-ignore lint/a11y/useSemanticElements: a group of toggle buttons, not a form's fieldset */}
            <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
              {KINDS.map((one) => (
                <button
                  key={one}
                  type="button"
                  aria-pressed={kind === one}
                  onClick={() => pickKind(one)}
                  className={cn(
                    "h-11 rounded-xl border px-3.5",
                    kind === one
                      ? "border-primary bg-accent font-semibold text-accent-foreground"
                      : "border-control-border bg-card",
                  )}
                >
                  {KIND_LABELS[one]} {formatNumber(counts[one])}
                </button>
              ))}
            </div>
          </div>
          {mode === "styled" ? (
            <ImagesBar hosts={hosts} allowed={images} onAllow={() => setImages(true)} />
          ) : null}
          <p className="text-muted-foreground text-sm" aria-live="polite">
            Showing {formatNumber(shown.length)} of {formatNumber(totals.entries)}{" "}
            entries
          </p>
          <TextModeProvider mode={mode}>
            <CardImages allowed={images}>
              <div
                ref={list}
                data-testid="lorebook-entries"
                className="relative rounded-2xl border bg-card"
                style={{
                  height: Math.max(virtualizer.getTotalSize(), shown.length ? 0 : 72),
                }}
              >
                {shown.length === 0 ? (
                  <p className="px-4 py-6 text-muted-foreground">
                    No entry matches this filter.
                  </p>
                ) : null}
                {items.map((item) => {
                  const one = shown[item.index];
                  return one ? (
                    <MeasuredRow
                      key={item.key}
                      index={item.index}
                      measure={virtualizer.measureElement}
                      resize={virtualizer.resizeItem}
                      open={open.has(one.index)}
                      top={item.start - scrollMargin}
                    >
                      <EntryRow
                        numbered={one}
                        open={open.has(one.index)}
                        onToggle={() => toggle(one.index)}
                        className={
                          item.index === shown.length - 1 ? "border-b-0" : undefined
                        }
                      />
                    </MeasuredRow>
                  ) : null;
                })}
              </div>
            </CardImages>
          </TextModeProvider>
        </>
      ) : (
        <p className="text-muted-foreground">This card has no lorebook.</p>
      )}
    </main>
  );
}
