import { useInfiniteQuery } from "@tanstack/react-query";
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

/**
 * The results as one long list, loaded a batch at a time as it is
 * scrolled. Every row of the search has its place from the start (the
 * total is known with the first batch), so a batch that arrives above
 * what is shown moves nothing; only the rows in view are drawn.
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
  const [start] = useState(() => Math.floor(at / BATCH) * BATCH);

  const posts = useInfiniteQuery({
    queryKey: ["posts", "auto", q, fields],
    initialPageParam: start,
    queryFn: ({ pageParam, signal }) => fetchPosts(q, pageParam, BATCH, fields, signal),
    getNextPageParam: (last, _pages, offset) =>
      offset + BATCH < (last.total ?? 0) ? offset + BATCH : undefined,
    getPreviousPageParam: (_first, _pages, offset) =>
      offset > 0 ? offset - BATCH : undefined,
  });

  const pages = posts.data?.pages ?? [];
  const offsets = (posts.data?.pageParams ?? []) as number[];
  const total = pages[0]?.total ?? null;
  const byIndex = useMemo(() => {
    const found = new Map<number, Post>();
    for (const [k, page] of (posts.data?.pages ?? []).entries()) {
      const offset = (posts.data?.pageParams[k] as number | undefined) ?? 0;
      for (const [i, post] of (page.results ?? []).entries()) {
        found.set(offset + i, post);
      }
    }
    return found;
  }, [posts.data]);
  const loadedStart = offsets[0] ?? start;
  const lastOffset = offsets.at(-1);
  const loadedEnd =
    lastOffset === undefined
      ? start
      : lastOffset + (pages.at(-1)?.results?.length ?? 0);

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
  const firstShown = (items[0]?.index ?? 0) * columns;
  const lastShown = ((items.at(-1)?.index ?? 0) + 1) * columns - 1;
  const scrolled = Math.max(0, (virtualizer.scrollOffset ?? 0) - scrollMargin);
  const firstVisible =
    rows > 0 ? Math.min(rows - 1, Math.floor(scrolled / rowHeight)) * columns : 0;

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

  // the batches the rows in view need, one request at a time
  useEffect(() => {
    if (!total || posts.isFetching || heading.current !== null) {
      return;
    }
    if (lastShown >= loadedEnd && posts.hasNextPage && !posts.isFetchNextPageError) {
      posts.fetchNextPage();
    } else if (
      firstShown < loadedStart &&
      posts.hasPreviousPage &&
      !posts.isFetchPreviousPageError
    ) {
      posts.fetchPreviousPage();
    }
  }, [total, posts, firstShown, lastShown, loadedStart, loadedEnd]);

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

  const failedBatch = posts.isFetchNextPageError || posts.isFetchPreviousPageError;
  return (
    <>
      <ResultsBar total={total} perPage="auto" onPerPage={onPerPage} />
      {posts.isError && !posts.data ? (
        <Failed error={posts.error} onRetry={() => posts.refetch()} />
      ) : null}
      {posts.isPending ? (
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
      {failedBatch ? (
        <Failed
          error={posts.error}
          onRetry={() =>
            posts.isFetchNextPageError
              ? posts.fetchNextPage()
              : posts.fetchPreviousPage()
          }
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
