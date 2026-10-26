import { ChevronDown, ChevronRight } from "lucide-react";
import { useId } from "react";
import { cn } from "@/lib/utils";
import { CardText } from "@/text/CardText";
import {
  detailsOf,
  entryTitle,
  formatNumber,
  isDisabled,
  modeOf,
  type Numbered,
} from "./lorebook";

/**
 * One lorebook entry: a line with its name, keys, mode, size and state,
 * which opens to its content and the details the card sets.
 */
export function EntryRow({
  numbered,
  open,
  onToggle,
  className,
}: {
  numbered: Numbered;
  open: boolean;
  onToggle(): void;
  className?: string;
}) {
  const { entry } = numbered;
  const id = useId();
  const disabled = isDisabled(entry);
  const Chevron = open ? ChevronDown : ChevronRight;
  const details = detailsOf(entry);
  return (
    <div data-entry={numbered.index} className={cn("border-b", className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
        className="flex min-h-14 w-full flex-wrap items-center gap-x-2.5 gap-y-1 px-4 py-2.5 text-left hover:bg-muted/50 focus-visible:outline-2 focus-visible:outline-ring"
      >
        <Chevron aria-hidden className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-40 font-semibold">{entryTitle(numbered)}</span>
        {(entry.keys ?? []).map((key, i) => (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: keys may repeat
            key={i}
            className="rounded-md bg-secondary px-2 py-0.5 font-mono text-secondary-foreground text-xs"
          >
            {key}
          </span>
        ))}
        <span className="ml-auto flex items-center gap-3 text-muted-foreground text-xs">
          <span>{modeOf(entry)}</span>
          <span>{formatNumber(entry.content?.length ?? 0)} chars</span>
          <span className={cn("font-medium", disabled ? "text-warn" : "text-ok")}>
            {disabled ? "disabled" : "enabled"}
          </span>
        </span>
      </button>
      {open ? (
        <div id={id} className="flex flex-col gap-2.5 px-4 pt-1 pb-4 sm:pl-11">
          {entry.content ? (
            <CardText text={entry.content} />
          ) : (
            <p className="text-muted-foreground">No content.</p>
          )}
          {details.length ? (
            <dl className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground text-xs">
              {details.map(([label, value]) => (
                <div key={label} className="flex gap-1">
                  <dt>{label}:</dt>
                  <dd className="break-all">{value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
