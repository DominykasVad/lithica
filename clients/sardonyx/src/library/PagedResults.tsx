import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { useTileLayout } from "./layout";
import { Paging } from "./Paging";
import { PostTile, TilePlaceholder } from "./PostTile";
import type { PerPage } from "./perPage";
import { fetchPosts } from "./posts";
import { Failed, NoResults, PastTheEnd, ResultsBar } from "./ResultsBar";
import { librarySearch } from "./search";

// how many placeholder tiles stand in for a page while it loads
const PLACEHOLDERS = 12;

/**
 * The results a page at a time: one request per page, from the page that
 * holds `at`. A page is a URL of its own, so the back button goes back a
 * page.
 */
export function PagedResults({
  q,
  at,
  size,
  fields,
  onPerPage,
}: {
  q: string;
  at: number;
  size: 50 | 100;
  fields: string;
  onPerPage(next: PerPage): void;
}) {
  const navigate = useNavigate();
  const grid = useRef<HTMLDivElement>(null);
  const layout = useTileLayout(grid);
  const offset = Math.floor(at / size) * size;

  // an offset within a page (from auto load, or a link) becomes its page
  useEffect(() => {
    if (offset !== at) {
      navigate({
        to: "/posts",
        search: librarySearch(q, offset),
        replace: true,
        resetScroll: false,
      });
    }
  }, [navigate, q, at, offset]);

  const page = useQuery({
    queryKey: ["posts", "page", q, offset, size, fields],
    queryFn: ({ signal }) => fetchPosts(q, offset, size, fields, signal),
  });
  const total = page.data?.total ?? null;
  const results = page.data?.results ?? [];

  return (
    <>
      <ResultsBar total={total} perPage={size} onPerPage={onPerPage} />
      {page.isError ? (
        <Failed error={page.error} onRetry={() => page.refetch()} />
      ) : null}
      <div
        ref={grid}
        className="grid justify-start"
        style={{
          gridTemplateColumns: `repeat(auto-fill, ${layout.tileWidth}px)`,
          gap: 20,
        }}
      >
        {page.isPending
          ? Array.from({ length: PLACEHOLDERS }, (_, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have nothing else
              <TilePlaceholder key={i} layout={layout} />
            ))
          : results.map((post) => (
              <PostTile
                key={post.id}
                post={post}
                layout={layout}
                from={librarySearch(q, offset)}
              />
            ))}
      </div>
      {page.isSuccess && results.length === 0 ? (
        total ? (
          <PastTheEnd q={q} />
        ) : (
          <NoResults q={q} />
        )
      ) : null}
      {total ? (
        <Paging
          list={{ to: "/posts", searchAt: (at) => librarySearch(q, at) }}
          page={offset / size}
          size={size}
          total={total}
        />
      ) : null}
    </>
  );
}
