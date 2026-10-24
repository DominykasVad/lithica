import { type ReactNode, useId, useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type Control,
  type FilterName,
  type FilterValues,
  FORMATS,
  type Format,
  readFilters,
  SPECS,
  type Spec,
  writeFilter,
} from "@/search/cardFilters";

function Custom({ control }: { control: Control<unknown> }) {
  return control.state === "custom" ? (
    <span className="ml-2 rounded bg-macro px-1.5 font-normal text-macro-foreground text-xs">
      custom
    </span>
  ) : null;
}

function Group({
  legend,
  control,
  children,
}: {
  legend: string;
  control: Control<unknown>;
  children: ReactNode;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1.5 font-semibold text-sm">
        {legend}
        <Custom control={control} />
      </legend>
      {children}
    </fieldset>
  );
}

/** A text field that writes its filter when it is left or Enter is pressed. */
function TextFilter({
  label,
  control,
  shown,
  type = "text",
  onCommit,
}: {
  label: string;
  control: Control<unknown>;
  shown: string;
  type?: "text" | "number";
  onCommit(text: string): void;
}) {
  const id = useId();
  const [text, setText] = useState(shown);
  // the query text changed elsewhere: show what it says now
  const [was, setWas] = useState(shown);
  if (shown !== was) {
    setWas(shown);
    setText(shown);
  }
  const commit = () => {
    if (text !== shown) {
      onCommit(text);
    }
  };
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="font-semibold text-sm">
        {label}
        <Custom control={control} />
      </label>
      <Input
        id={id}
        type={type}
        min={type === "number" ? 0 : undefined}
        placeholder={control.state === "custom" ? "custom" : "any"}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        className="h-11 bg-background"
      />
    </div>
  );
}

function Choices<T extends string>({
  legend,
  control,
  options,
  labels,
  onChange,
}: {
  legend: string;
  control: Control<T[]>;
  options: readonly T[];
  labels: Record<T, string>;
  onChange(next: T[]): void;
}) {
  const id = useId();
  const chosen = control.state === "set" ? control.value : [];
  return (
    <Group legend={legend} control={control}>
      {options.map((option) => (
        <div key={option} className="flex items-center gap-2">
          <Checkbox
            id={`${id}-${option}`}
            checked={chosen.includes(option)}
            onCheckedChange={(checked) =>
              onChange(
                options.filter((one) =>
                  one === option ? checked === true : chosen.includes(one),
                ),
              )
            }
          />
          <Label htmlFor={`${id}-${option}`} className="font-normal">
            {labels[option]}
          </Label>
        </div>
      ))}
    </Group>
  );
}

const SPEC_LABELS: Record<Spec, string> = { v1: "V1", v2: "V2", v3: "V3" };
const FORMAT_LABELS: Record<Format, string> = { png: "PNG", charx: "CHARX" };
const LOREBOOK = [
  ["any", "Any"],
  ["yes", "With lorebook"],
  ["no", "Without"],
] as const;

/**
 * The card filters. They read the query text and write into it: changing
 * one replaces only the tokens it owns, and is a new search.
 */
export function CardFilterPanel({
  query,
  onChange,
}: {
  query: string;
  onChange(next: string): void;
}) {
  const name = useId();
  const filters = readFilters(query);
  const set = <Name extends FilterName>(
    filter: Name,
    value: FilterValues[Name] | null,
  ) => onChange(writeFilter(query, filter, value));
  const lorebook = filters.lorebook.state === "set" ? filters.lorebook.value : null;

  return (
    <aside
      aria-label="Card filters"
      className="flex flex-[1_1_220px] flex-col gap-5 self-start rounded-2xl border bg-card p-4 md:max-w-64"
    >
      <TextFilter
        label="Creator"
        control={filters.creator}
        shown={filters.creator.state === "set" ? filters.creator.value : ""}
        onCommit={(text) => set("creator", text.trim() ? text : null)}
      />
      <Choices
        legend="Spec"
        control={filters.spec}
        options={SPECS}
        labels={SPEC_LABELS}
        onChange={(next) => set("spec", next)}
      />
      <Choices
        legend="File"
        control={filters.format}
        options={FORMATS}
        labels={FORMAT_LABELS}
        onChange={(next) => set("format", next)}
      />
      <Group legend="Lorebook" control={filters.lorebook}>
        {LOREBOOK.map(([value, label]) => (
          <label key={value} className="flex items-center gap-2">
            <input
              type="radio"
              name={name}
              value={value}
              checked={
                filters.lorebook.state !== "custom" && (lorebook ?? "any") === value
              }
              onChange={() => set("lorebook", value === "any" ? null : value)}
              className="size-4 accent-primary"
            />
            {label}
          </label>
        ))}
      </Group>
      <TextFilter
        label="Greetings, at least"
        type="number"
        control={filters.greetings}
        shown={filters.greetings.state === "set" ? String(filters.greetings.value) : ""}
        onCommit={(text) => {
          const count = Number.parseInt(text, 10);
          set("greetings", Number.isFinite(count) && count > 0 ? count : null);
        }}
      />
      <p className="text-muted-foreground text-xs">
        Filters write into the search line above, so a search can always be copied as
        text.
      </p>
    </aside>
  );
}
