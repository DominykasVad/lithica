import { Link } from "@tanstack/react-router";
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// pages either side of the current one that get a number
const AROUND = 2;

const step =
  "flex h-11 min-w-11 items-center justify-center rounded-lg border px-3 text-sm";

/** The list a pager moves in: its page, and its search at an offset. */
export interface PagedList {
  to: "/posts";
  searchAt(offset: number): object;
}

function PageLink({
  list,
  page,
  size,
  label,
  current = false,
  children,
}: {
  list: PagedList;
  page: number;
  size: number;
  label: string;
  current?: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      to={list.to}
      // the search of the list's own route, which its searchAt writes
      search={list.searchAt(page * size) as never}
      aria-label={label}
      aria-current={current ? "page" : undefined}
      className={cn(
        step,
        current
          ? "border-primary bg-primary font-semibold text-primary-foreground"
          : "text-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      {children}
    </Link>
  );
}

function Unavailable({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span aria-disabled="true" className={cn(step, "opacity-40")}>
      {children}
      <span className="sr-only">{label}</span>
    </span>
  );
}

/** First, previous, the pages around this one, next and last. */
export function Paging({
  list,
  page,
  size,
  total,
}: {
  list: PagedList;
  page: number;
  size: number;
  total: number;
}) {
  const last = Math.max(0, Math.ceil(total / size) - 1);
  // one page, or a page past the end (which links back to the first)
  if (last === 0 || page > last) {
    return null;
  }
  const from = Math.max(0, page - AROUND);
  const to = Math.min(last, page + AROUND);
  const numbers = Array.from({ length: to - from + 1 }, (_, i) => from + i);
  const move = (target: number, label: string, icon: ReactNode) =>
    target < 0 || target > last || target === page ? (
      <Unavailable label={label}>{icon}</Unavailable>
    ) : (
      <PageLink list={list} page={target} size={size} label={label}>
        {icon}
      </PageLink>
    );
  return (
    <nav aria-label="Pages" className="flex flex-wrap justify-center gap-1.5 pt-2">
      {move(0, "First page", <ChevronFirst className="size-4" />)}
      {move(page - 1, "Previous page", <ChevronLeft className="size-4" />)}
      {numbers.map((number) => (
        <PageLink
          key={number}
          list={list}
          page={number}
          size={size}
          label={`Page ${number + 1}`}
          current={number === page}
        >
          {number + 1}
        </PageLink>
      ))}
      {move(page + 1, "Next page", <ChevronRight className="size-4" />)}
      {move(last, "Last page", <ChevronLast className="size-4" />)}
    </nav>
  );
}
