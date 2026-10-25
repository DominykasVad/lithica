import { type ReactNode, useId } from "react";
import { Button } from "@/components/ui/button";
import { CompletionInput } from "@/search/CompletionInput";

/**
 * The query text, in the engine's syntax, with tags completed for the
 * token being typed.
 */
export function SearchBox({
  value,
  onChange,
  onSubmit,
  children,
}: {
  value: string;
  onChange(next: string): void;
  onSubmit(): void;
  /** more buttons, after Search */
  children?: ReactNode;
}) {
  const id = useId();
  return (
    // biome-ignore lint/a11y/useSemanticElements: a form, so that Enter searches; role says it is the search
    <form
      role="search"
      className="flex flex-wrap items-center gap-2.5"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label htmlFor={`${id}-query`} className="sr-only">
        Search query
      </label>
      <CompletionInput
        id={`${id}-query`}
        value={value}
        onChange={onChange}
        className="flex-[1_1_420px]"
      />
      <Button type="submit" className="h-12 rounded-xl px-5">
        Search
      </Button>
      {children}
    </form>
  );
}
