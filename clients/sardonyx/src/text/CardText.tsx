import { createContext, type ReactNode, useContext, useState } from "react";
import Markdown, { type Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { cn } from "@/lib/utils";
import {
  htmlAsText,
  imagesAsText,
  isWebUrl,
  linksWithUrl,
  MACRO_CLASS,
  macros,
  splitMacros,
} from "./rehype";

/**
 * The ways card text can be shown, in the switch's order: Readable
 * (sanitised Markdown, HTML as its text) and Source (the text as written).
 * A mode is one entry here and one renderer below.
 */
export const TEXT_MODES = [
  { id: "readable", label: "Readable" },
  { id: "source", label: "Source" },
] as const;

export type TextMode = (typeof TEXT_MODES)[number]["id"];

const STORAGE_KEY = "sardonyx.cardText";
const DEFAULT: TextMode = "readable";
// what the setting was called before, read as the mode it is now
const RENAMED: Record<string, TextMode> = { formatted: "readable", plain: "source" };

function isMode(value: string | null): value is TextMode {
  return TEXT_MODES.some((one) => one.id === value);
}

function stored(): TextMode {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return isMode(value) ? value : (RENAMED[value ?? ""] ?? DEFAULT);
  } catch {
    // storage may be blocked
    return DEFAULT;
  }
}

/** The choice of this browser, kept in localStorage. */
export function useTextMode(): [TextMode, (next: TextMode) => void] {
  const [mode, setMode] = useState<TextMode>(stored);
  const choose = (next: TextMode) => {
    setMode(next);
    try {
      if (next === DEFAULT) {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, next);
      }
    } catch {
      // not kept; it lasts as long as the page
    }
  };
  return [mode, choose];
}

const TextModeContext = createContext<TextMode>(DEFAULT);

/** The mode every CardText inside shows its text in. */
export function TextModeProvider({
  mode,
  children,
}: {
  mode: TextMode;
  children: ReactNode;
}) {
  return <TextModeContext value={mode}>{children}</TextModeContext>;
}

// the order matters: what the sanitiser would drop is made text first,
// and the macros' spans come after it, which would take their classes
const REHYPE = [htmlAsText, imagesAsText, linksWithUrl, rehypeSanitize, macros];

const COMPONENTS: Components = {
  a({ href, children }) {
    // only http(s) links are left as links (linksWithUrl); checked again
    return href && isWebUrl(href) ? (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow ugc">
        {children}
      </a>
    ) : (
      children
    );
  },
};

// Markdown's elements, readable without a typography plugin. A line break
// in a paragraph is kept: cards are written line by line.
const MARKDOWN_CLASS = cn(
  "flex flex-col gap-3",
  "[&_p]:whitespace-pre-line",
  "[&_a]:text-link [&_a]:underline",
  "[&_em]:italic [&_strong]:font-semibold",
  "[&_ul]:list-disc [&_ul]:pl-6 [&_ol]:list-decimal [&_ol]:pl-6",
  "[&_blockquote]:border-l-2 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground",
  "[&_code]:font-mono [&_code]:text-[0.875em] [&_pre]:overflow-x-auto [&_pre]:whitespace-pre-wrap",
  "[&_h1]:font-semibold [&_h1]:font-serif [&_h1]:text-xl",
  "[&_h2]:font-semibold [&_h2]:font-serif [&_h2]:text-lg",
  "[&_h3]:font-semibold [&_h4]:font-semibold [&_h5]:font-semibold [&_h6]:font-semibold",
  "[&_hr]:border-border",
);

/** Text with its macros styled, every character as it is. */
export function WithMacros({ text }: { text: string }) {
  return splitMacros(text).map((piece, i) =>
    i % 2 ? (
      // biome-ignore lint/suspicious/noArrayIndexKey: the pieces of one text, in order
      <span key={i} data-macro="" className={MACRO_CLASS}>
        {piece}
      </span>
    ) : (
      piece
    ),
  );
}

const RENDERERS: Record<
  TextMode,
  (props: { text: string; className?: string }) => ReactNode
> = {
  readable: ({ text, className }) => (
    <div
      data-text="readable"
      className={cn("max-w-[75ch] break-words", MARKDOWN_CLASS, className)}
    >
      <Markdown rehypePlugins={REHYPE} components={COMPONENTS}>
        {text}
      </Markdown>
    </div>
  ),
  source: ({ text, className }) => (
    <div
      data-text="source"
      className={cn("max-w-[75ch] whitespace-pre-wrap break-words", className)}
    >
      <WithMacros text={text} />
    </div>
  ),
};

/**
 * Text of a card, as the browser's choice says, at a reading width:
 * readable (Markdown, sanitised, HTML as its text) or its source.
 */
export function CardText({ text, className }: { text: string; className?: string }) {
  const Render = RENDERERS[useContext(TextModeContext)];
  return <Render text={text} className={className} />;
}

/** The switch between the modes of card text. */
export function TextModeSwitch({
  mode,
  onChange,
}: {
  mode: TextMode;
  onChange(next: TextMode): void;
}) {
  return (
    // biome-ignore lint/a11y/useSemanticElements: a group of toggle buttons, not a form's fieldset
    <div role="group" aria-label="Card text" className="flex rounded-lg border p-0.5">
      {TEXT_MODES.map((one) => (
        <button
          key={one.id}
          type="button"
          aria-pressed={mode === one.id}
          onClick={() => onChange(one.id)}
          className={cn(
            "rounded-md px-3 py-1 text-sm",
            mode === one.id
              ? "bg-accent font-semibold text-accent-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {one.label}
        </button>
      ))}
    </div>
  );
}

/** Splits example messages into the dialogues their `<START>` lines begin. */
export function examples(text: string): string[] {
  return text
    .split(/^[ \t]*<START>[ \t]*$/im)
    .map((one) => one.replace(/^\n+|\n+$/g, ""))
    .filter((one) => one.trim());
}
