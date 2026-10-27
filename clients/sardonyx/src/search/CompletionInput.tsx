import { useQuery } from "@tanstack/react-query";
import {
  type KeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import { cn } from "@/lib/utils";
import {
  type Completing,
  completing,
  completingName,
  suggestionQuery,
  take,
  takeName,
} from "./completion";

// typing rests this long before the site is asked for tags
const DEBOUNCE_MS = 150;
// a multi-line field grows with its text up to this many pixels, then scrolls
export const MAX_FIELD_HEIGHT = 192;
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
 * A text field that completes tags for the word being typed (the ARIA
 * combobox pattern: the list follows the input, arrows move in it, Enter
 * or Tab takes, Escape closes). Its text is either a query in the engine's
 * syntax (a tag taken is escaped, named tokens are left alone) or a list
 * of tag names (`mode="names"`: every word a name, as it is).
 *
 * `multiline`: a field that wraps, for a long list of tags, growing with
 * its text up to MAX_FIELD_HEIGHT and scrolling beyond. Its text is still
 * one line of words separated by spaces: Enter adds no line break, and a
 * pasted one becomes a space. A textarea cannot be a combobox (ARIA in
 * HTML), so it is a text box that owns the list (aria-controls,
 * aria-activedescendant), as a combobox does.
 */
export function CompletionInput({
  id,
  value,
  onChange,
  mode = "query",
  multiline = false,
  placeholder,
  className,
  inputClassName,
}: {
  /** the input's id, for its label */
  id: string;
  value: string;
  onChange(next: string): void;
  mode?: "query" | "names";
  multiline?: boolean;
  placeholder?: string;
  className?: string;
  inputClassName?: string;
}) {
  const names = mode === "names";
  const listId = `${id}-tags`;
  const input = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
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

  // a multi-line field is as tall as its text, up to its most
  // biome-ignore lint/correctness/useExhaustiveDependencies: the height follows the text
  useLayoutEffect(() => {
    const field = input.current;
    if (multiline && field) {
      field.style.height = "auto";
      field.style.height = `${Math.min(field.scrollHeight + 2, MAX_FIELD_HEIGHT)}px`;
    }
  }, [multiline, value]);

  const close = () => {
    setTarget(null);
    setActive(-1);
  };

  const choose = (name: string) => {
    if (!target) {
      return;
    }
    const taken = names ? takeName(value, target, name) : take(value, target, name);
    cursor.current = taken.cursor;
    onChange(taken.query);
    close();
  };

  const keyDown = (event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (multiline && event.key === "Enter" && !(open && active >= 0)) {
      // the text stays one line of words: no line break
      event.preventDefault();
      close();
      return;
    }
    if (!open) {
      return;
    }
    if (event.key === "Enter" && active < 0) {
      // Enter with nothing chosen is the form's (a search): the list closes
      close();
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
    <div className={cn("relative min-w-0", className)}>
      {multiline ? (
        <textarea
          ref={input}
          id={id}
          rows={1}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            open && active >= 0 ? `${listId}-${active}` : undefined
          }
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(event) => {
            // a line break pasted in is a space: the same length, the cursor stays
            const text = event.target.value.replace(/[\r\n]/g, " ");
            onChange(text);
            const at = event.target.selectionStart ?? text.length;
            setTarget(names ? completingName(text, at) : completing(text, at));
            setActive(-1);
          }}
          onKeyDown={keyDown}
          onBlur={close}
          placeholder={placeholder}
          style={{ maxHeight: MAX_FIELD_HEIGHT }}
          className={cn(
            "block w-full resize-none overflow-x-hidden overflow-y-auto whitespace-pre-wrap wrap-anywhere rounded-xl border border-control-border bg-card px-4 py-2.5 font-mono text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring",
            inputClassName,
          )}
        />
      ) : (
        <input
          ref={input}
          id={id}
          type={names ? "text" : "search"}
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
            const at = event.target.selectionStart ?? event.target.value.length;
            setTarget(
              names
                ? completingName(event.target.value, at)
                : completing(event.target.value, at),
            );
            setActive(-1);
          }}
          onKeyDown={keyDown}
          onBlur={close}
          placeholder={placeholder}
          className={cn(
            "h-12 w-full rounded-xl border border-control-border bg-card px-4 font-mono text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring",
            inputClassName,
          )}
        />
      )}
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
  );
}
