import { EyeOff } from "lucide-react";
import {
  type CSSProperties,
  createContext,
  type ReactNode,
  useContext,
  useState,
} from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const SHOW_KEY = "sardonyx.showNsfw";
const REVEALED_KEY = "sardonyx.revealedNsfw";

function storedShow(): boolean {
  try {
    return localStorage.getItem(SHOW_KEY) === "true";
  } catch {
    // storage may be blocked: off
    return false;
  }
}

function storedRevealed(): Set<number> {
  try {
    const stored = JSON.parse(sessionStorage.getItem(REVEALED_KEY) ?? "[]");
    if (Array.isArray(stored)) {
      return new Set(stored.filter((id): id is number => Number.isSafeInteger(id)));
    }
  } catch {
    // nothing usable stored
  }
  return new Set();
}

const NsfwContext = createContext<{
  show: boolean;
  setShow(show: boolean): void;
  revealed: ReadonlySet<number>;
  reveal(id: number): void;
} | null>(null);

/**
 * Whether NSFW posts are shown as any other ("Show NSFW", this browser's
 * choice, off unless chosen), and the posts revealed one at a time while
 * it is off: for this tab's session, kept in its sessionStorage.
 */
export function NsfwProvider({ children }: { children: ReactNode }) {
  const [show, setShowState] = useState(storedShow);
  const [revealed, setRevealed] = useState(storedRevealed);

  const setShow = (next: boolean) => {
    setShowState(next);
    try {
      if (next) {
        localStorage.setItem(SHOW_KEY, "true");
      } else {
        localStorage.removeItem(SHOW_KEY);
      }
    } catch {
      // not kept; it lasts as long as the page
    }
  };
  const reveal = (id: number) => {
    const next = new Set(revealed).add(id);
    setRevealed(next);
    try {
      sessionStorage.setItem(REVEALED_KEY, JSON.stringify([...next]));
    } catch {
      // not kept; it lasts as long as the page
    }
  };
  return (
    <NsfwContext.Provider value={{ show, setShow, revealed, reveal }}>
      {children}
    </NsfwContext.Provider>
  );
}

function useNsfwContext() {
  const context = useContext(NsfwContext);
  if (!context) {
    throw new Error("useNsfw outside of NsfwProvider");
  }
  return context;
}

/** The "Show NSFW" switch. */
export function useShowNsfw(): [boolean, (show: boolean) => void] {
  const { show, setShow } = useNsfwContext();
  return [show, setShow];
}

/**
 * Whether this post is kept out of sight: it is NSFW (the site says so,
 * `nsfw`), "Show NSFW" is off, and it was not revealed. `reveal` shows it,
 * and only it.
 */
export function useNsfwHidden(post: { id?: number; nsfw?: boolean } | undefined): {
  hidden: boolean;
  reveal(): void;
} {
  const { show, revealed, reveal } = useNsfwContext();
  const id = post?.id;
  return {
    hidden: post?.nsfw === true && !show && !(id !== undefined && revealed.has(id)),
    reveal: () => {
      if (id !== undefined) {
        reveal(id);
      }
    },
  };
}

/** How a hidden picture is drawn: blurred past knowing, larger so its edges stay soft. */
export const BLURRED = "scale-110 blur-2xl";

/** The "NSFW" label and the click that reveals the post, over what it hides. */
export function NsfwCover({
  onReveal,
  className,
  style,
  compact = false,
}: {
  onReveal(): void;
  className?: string;
  style?: CSSProperties;
  /** a tile's: the label and a smaller button */
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "absolute inset-0 flex flex-col items-center justify-center gap-2 bg-background/40 p-2 text-center",
        className,
      )}
      style={style}
    >
      <span className="inline-flex items-center gap-1 rounded-md bg-card px-2 py-0.5 font-semibold text-card-foreground text-xs">
        <EyeOff className="size-3.5" aria-hidden />
        NSFW
      </span>
      <Button
        type="button"
        variant="secondary"
        size={compact ? "sm" : "default"}
        onClick={(event) => {
          // a tile's cover is over its link: revealing does not open the post
          event.preventDefault();
          event.stopPropagation();
          onReveal();
        }}
      >
        Show this post
      </Button>
    </div>
  );
}

/** A NSFW card's text, while it is hidden: the same click as its picture. */
export function HiddenText({ onReveal }: { onReveal(): void }) {
  return (
    <section
      aria-label="Card text hidden"
      className="relative flex min-h-64 flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border bg-card p-6 text-center"
    >
      <p className="text-muted-foreground text-sm">
        This post is NSFW: its card text is hidden while NSFW is not shown.
      </p>
      <NsfwCover onReveal={onReveal} className="static bg-transparent" />
    </section>
  );
}
