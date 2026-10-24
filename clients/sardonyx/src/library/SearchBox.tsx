import { useQuery } from "@tanstack/react-query";
import {
  type KeyboardEvent,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  type Completing,
  completing,
  suggestionQuery,
  take,
} from "@/search/completion";

// typing rests this long before the site is asked for tags
const DEBOUNCE_MS = 150;
const SUGGESTIONS = 10;

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/**
 * The query text, in the engine's syntax, with tags completed for the
 * token being typed (the ARIA combobox pattern: the list follows the
 * input, arrows move in it, Enter or Tab takes, Escape closes).
 */
export function SearchBox({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange(next: string): void;
  onSubmit(): void;
}) {
  const id = useId();
  const listId = `${id}-tags`;
  const input = useRef<HTMLInputElement>(null);
  const [target, setTarget] = useState<Completing | null>(null);
  const [active, setActive] = useState(-1);
  const cursor = useRef<number | null>(null);

  const prefix = target?.prefix ?? "";
  const asked = useDebounced(prefix, DEBOUNCE_MS);
  const tags = useQuery({
    queryKey: ["tags", "completion", asked],
    enabled: asked !== "",
    staleTime: 30_000,
    // a request for an older prefix is let go of: its answer is not shown
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/tags", {
          params: {
            query: {
              query: suggestionQuery(asked),
              limit: SUGGESTIONS,
              fields: "names,category,usages",
            },
          },
          signal,
        }),
      ),
  });
  // only what was asked for the token as it is now
  const suggestions =
    target && asked === prefix
      ? (tags.data?.results ?? []).filter((tag) => tag.names?.[0])
      : [];
  const open = suggestions.length > 0;

  // the cursor goes after a taken tag once the input shows it
  useLayoutEffect(() => {
    if (cursor.current !== null && input.current) {
      input.current.setSelectionRange(cursor.current, cursor.current);
      cursor.current = null;
    }
  });

  const close = () => {
    setTarget(null);
    setActive(-1);
  };

  const choose = (name: string) => {
    if (!target) {
      return;
    }
    const taken = take(value, target, name);
    cursor.current = taken.cursor;
    onChange(taken.query);
    close();
  };

  const keyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!open) {
      return;
    }
    const chosen = suggestions[active]?.names?.[0];
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const count = suggestions.length;
      // round from the last to the first, and back
      setActive((current) =>
        event.key === "ArrowDown"
          ? (current + 1) % count
          : current <= 0
            ? count - 1
            : current - 1,
      );
    } else if ((event.key === "Enter" || event.key === "Tab") && chosen) {
      event.preventDefault();
      choose(chosen);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  };

  return (
    // biome-ignore lint/a11y/useSemanticElements: a form, so that Enter searches; role says it is the search
    <form
      role="search"
      className="flex flex-wrap items-center gap-2.5"
      onSubmit={(event) => {
        event.preventDefault();
        close();
        onSubmit();
      }}
    >
      <label htmlFor={`${id}-query`} className="sr-only">
        Search query
      </label>
      <div className="relative min-w-0 flex-[1_1_420px]">
        <input
          ref={input}
          id={`${id}-query`}
          type="search"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            open && active >= 0 ? `${listId}-${active}` : undefined
          }
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setTarget(
              completing(
                event.target.value,
                event.target.selectionStart ?? event.target.value.length,
              ),
            );
            setActive(-1);
          }}
          onKeyDown={keyDown}
          onBlur={close}
          className="h-12 w-full rounded-xl border border-input bg-card px-4 font-mono text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <div
          id={listId}
          role="listbox"
          aria-label="Tags"
          hidden={!open}
          className="absolute top-full right-0 left-0 z-20 mt-1 max-h-80 overflow-auto rounded-xl border bg-popover p-1 text-popover-foreground shadow-md"
        >
          {suggestions.map((tag, index) => {
            const name = tag.names?.[0] ?? "";
            return (
              // biome-ignore lint/a11y/useFocusableInteractive lint/a11y/useKeyWithClickEvents: an option of the combobox: the focus stays in the input, whose keys choose it (aria-activedescendant)
              <div
                key={name}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === active}
                // keeps the focus in the input, so the list stays open
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(name)}
                onMouseEnter={() => setActive(index)}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2",
                  index === active && "bg-accent text-accent-foreground",
                )}
              >
                <span className="font-mono">{name}</span>
                <span className="text-muted-foreground text-xs">{tag.category}</span>
                <span className="ml-auto text-muted-foreground text-xs">
                  {tag.usages}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      <Button type="submit" className="h-12 rounded-xl px-5">
        Search
      </Button>
    </form>
  );
}
