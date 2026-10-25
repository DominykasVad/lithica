import { useQueries } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { ArrowUp } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { GAP, useTileLayout } from "./layout";
import { PostTile, TilePlaceholder } from "./PostTile";
import type { PerPage } from "./perPage";
import { BATCH, fetchPosts, type Post } from "./posts";
import { Failed, NoResults, ResultsBar } from "./ResultsBar";
import { librarySearch } from "./search";

const PLACEHOLDERS = 12;
// how long scrolling rests before the position is written into the URL
const SETTLE_MS = 300;
// how long it rests before the batches in view are asked for: a drag
// across the list asks only for where it stops
const ASK_MS = 150;
// batches asked beyond those in view, each way
const AHEAD = 1;

/**
 * The results as one long list, loaded a batch at a time as it is
 * scrolled. Every row of the search has its place from the start (the
 * total is known with the first batch), so a batch that arrives above
 * what is shown moves nothing; only the rows in view are drawn.
 *
 * Each batch is its own query, by its offset: a jump far down asks for
 * the batches there, not for those in between. Rows of a batch not here
 * yet are placeholders.
 *
 * `at` opens the list there. Scrolling writes the first result in view
 * back into the URL without a history entry: back goes to the search
 * before, not to where this one was scrolled.
 */
export function AutoResults({
  q,
  at,
  fields,
  onPerPage,
}: {
  q: string;
  at: number;
  fields: string;
  onPerPage(next: PerPage): void;
}) {
  const navigate = useNavigate();
  const list = useRef<HTMLDivElement>(null);
  const layout = useTileLayout(list);
  const { columns } = layout;
  const rowHeight = layout.tileHeight + GAP;
  // loading starts with the batch that holds `at` when the list opens
  const [start] = useState(() => Math.floor(at / BATCH));
  const [asked, setAsked] = useState<number[]>(() => [start]);

  const batches = useQueries({
    queries: asked.map((batch) => ({
      queryKey: ["posts", "auto", q, fields, batch * BATCH],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        fetchPosts(q, batch * BATCH, BATCH, fields, signal),
      // scrolling back to a batch shows it as it was, without asking again
      staleTime: 60_000,
    })),
  });

  // the total of the newest answer: posts added or removed meanwhile
  // resize the list. Kept while the batches asked are all on their way.
  const known = useRef<{ total: number; updatedAt: number } | null>(null);
  for (const batch of batches) {
    const total = batch.data?.total;
    if (
      total !== undefined &&
      batch.dataUpdatedAt > (known.current?.updatedAt ?? Number.NEGATIVE_INFINITY)
    ) {
      known.current = { total, updatedAt: batch.dataUpdatedAt };
    }
  }
  const total = known.current?.total ?? null;

  const byIndex = useMemo(() => {
    const found = new Map<number, Post>();
    for (const [k, batch] of batches.entries()) {
      const offset = (asked[k] ?? 0) * BATCH;
      for (const [i, post] of (batch.data?.results ?? []).entries()) {
        found.set(offset + i, post);
      }
    }
    return found;
  }, [batches, asked]);

  const rows = total ? Math.ceil(total / columns) : 0;
  const scrollMargin = list.current?.offsetTop ?? 0;
  const virtualizer = useWindowVirtualizer({
    count: rows,
    estimateSize: () => rowHeight,
    overscan: 2,
    scrollMargin,
  });
  // biome-ignore lint/correctness/useExhaustiveDependencies: measured anew when the layout changes
  useEffect(() => {
    virtualizer.measure();
  }, [virtualizer, rowHeight, columns]);

  const items = virtualizer.getVirtualItems();
  const scrolled = Math.max(0, (virtualizer.scrollOffset ?? 0) - scrollMargin);
  const firstVisible =
    rows > 0 ? Math.min(rows - 1, Math.floor(scrolled / rowHeight)) * columns : 0;
  const viewHeight = virtualizer.scrollRect?.height ?? window.innerHeight;
  const lastVisible =
    rows > 0
      ? (Math.min(rows - 1, Math.floor((scrolled + viewHeight) / rowHeight)) + 1) *
          columns -
        1
      : 0;

  // `at` as last written here, or opened; another one is scrolled to
  const written = useRef<number | null>(null);
  // where a scroll to `at` is going, until the window is there: what is in
  // view before then is not where the list is
  const heading = useRef<number | null>(null);
  const scrollOffset = virtualizer.scrollOffset ?? 0;
  if (heading.current !== null && Math.abs(scrollOffset - heading.current) < 1) {
    heading.current = null;
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: scrolls once per new `at`
  useEffect(() => {
    if (!rows || total === null || at === written.current) {
      return;
    }
    written.current = at;
    const row = Math.floor(Math.min(at, total - 1) / columns);
    const target = at > 0 ? (virtualizer.getOffsetForIndex(row, "start")?.[0] ?? 0) : 0;
    if (Math.abs(target - scrollOffset) < 1) {
      return;
    }
    heading.current = target;
    // after the router has set the window's scroll for the new page (to
    // the top, or where it was), which it does once the page is drawn
    let done = false;
    const timer = setTimeout(() => {
      done = true;
      virtualizer.scrollToIndex(row, { align: "start" });
    });
    return () => {
      clearTimeout(timer);
      if (!done) {
        // not scrolled: the next run of this effect is to do it
        written.current = null;
        heading.current = null;
      }
    };
  }, [at, rows]);

  // the batches the rows in the window need, and one more each way, once
  // scrolling rests and the list is where it is going
  const lastBatch = total ? Math.ceil(total / BATCH) - 1 : 0;
  const firstInView = Math.floor(firstVisible / BATCH);
  const lastInView = Math.floor(lastVisible / BATCH);
  const from = Math.max(0, firstInView - AHEAD);
  const to = Math.min(lastBatch, lastInView + AHEAD);
  useEffect(() => {
    if (!total) {
      return;
    }
    const timer = setTimeout(() => {
      if (written.current === null || heading.current !== null) {
        return;
      }
      const next = Array.from(
        { length: Math.max(0, to - from + 1) },
        (_, i) => from + i,
      );
      setAsked((current) =>
        current.length === next.length && current.every((one, i) => one === next[i])
          ? current
          : next,
      );
    }, ASK_MS);
    return () => clearTimeout(timer);
  }, [total, from, to]);

  useEffect(() => {
    if (
      !total ||
      written.current === null ||
      heading.current !== null ||
      firstVisible === written.current
    ) {
      return;
    }
    const timer = setTimeout(() => {
      written.current = firstVisible;
      navigate({
        to: "/posts",
        search: librarySearch(q, firstVisible),
        replace: true,
        resetScroll: false,
      });
    }, SETTLE_MS);
    return () => clearTimeout(timer);
  }, [firstVisible, total, q, navigate]);

  // a batch in view that could not be loaded; the rows of the others stay
  const failed = batches.filter(
    (batch, k) =>
      batch.isError &&
      (total === null ||
        ((asked[k] ?? 0) >= firstInView && (asked[k] ?? 0) <= lastInView)),
  );
  const pending = total === null && batches.every((batch) => batch.isPending);
  return (
    <>
      <ResultsBar total={total} perPage="auto" onPerPage={onPerPage} />
      {pending ? (
        <div className="flex flex-wrap" style={{ gap: GAP }}>
          {Array.from({ length: PLACEHOLDERS }, (_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have nothing else
            <TilePlaceholder key={i} layout={layout} />
          ))}
        </div>
      ) : null}
      {total === 0 ? <NoResults q={q} /> : null}
      <div
        ref={list}
        data-testid="auto-list"
        className="relative w-full"
        style={{ height: virtualizer.getTotalSize() }}
      >
        {items.map((item) => (
          <div
            key={item.key}
            className="absolute top-0 left-0 flex w-full"
            style={{
              height: rowHeight,
              gap: GAP,
              transform: `translateY(${item.start - scrollMargin}px)`,
            }}
          >
            {Array.from({ length: columns }, (_, column) => {
              const index = item.index * columns + column;
              if (total === null || index >= total) {
                return null;
              }
              const post = byIndex.get(index);
              return post ? (
                <PostTile key={post.id} post={post} layout={layout} />
              ) : (
                <TilePlaceholder key={`at-${index}`} layout={layout} />
              );
            })}
          </div>
        ))}
      </div>
      {failed[0] ? (
        <Failed
          error={failed[0].error}
          onRetry={() => {
            for (const batch of failed) {
              batch.refetch();
            }
          }}
        />
      ) : null}
      {total ? (
        <div className="sticky bottom-4 ml-auto flex w-fit items-center gap-3 rounded-lg border bg-card px-3 py-2 text-sm shadow-sm">
          <span>
            {firstVisible + 1} of {total}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => window.scrollTo({ top: 0 })}
          >
            <ArrowUp />
            Back to top
          </Button>
        </div>
      ) : null}
    </>
  );
}
