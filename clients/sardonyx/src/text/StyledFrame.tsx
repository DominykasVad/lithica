import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CONTENT_MESSAGE,
  FRAME_SANDBOX,
  FRAME_URL,
  heightFrom,
  styledHtml,
} from "./styled";

// a frame is at most this share of the window high, and scrolls inside
const MAX_SHARE = 0.8;
// its height before it has said how high it is
const FIRST_HEIGHT = 120;

const ImagesContext = createContext(false);

/**
 * Whether the frames inside may load the card's pictures and fonts (from
 * https): the viewer's choice for one card, never kept.
 */
export function CardImages({
  allowed,
  children,
}: {
  allowed: boolean;
  children: ReactNode;
}) {
  return <ImagesContext value={allowed}>{children}</ImagesContext>;
}

// the app's colours and font, for the frame to show text in them
function theme(): Record<string, string> {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return {
    font: getComputedStyle(document.body).fontFamily,
    foreground: read("--foreground"),
    link: read("--link"),
    macro: read("--macro"),
    "macro-foreground": read("--macro-foreground"),
  };
}

function useMaxHeight(): number {
  const [max, setMax] = useState(() => Math.round(window.innerHeight * MAX_SHARE));
  useEffect(() => {
    const onResize = () => setMax(Math.round(window.innerHeight * MAX_SHARE));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return max;
}

/**
 * Card text in its frame: sandboxed (no same origin, so no session, storage
 * or page of the app), its HTML sent in by message, its height taken from
 * the one message the frame sends, up to most of the window.
 */
export function StyledFrame({ text, className }: { text: string; className?: string }) {
  const images = useContext(ImagesContext);
  const frame = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState<number | null>(null);
  const max = useMaxHeight();
  const html = useMemo(() => styledHtml(text), [text]);
  const src = images ? FRAME_URL.images : FRAME_URL.plain;

  // the frame's window is opaque: it can only be posted to as "*"
  const send = () =>
    frame.current?.contentWindow?.postMessage(
      { type: CONTENT_MESSAGE, html, theme: theme() },
      "*",
    );

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const reported = heightFrom(event, frame.current?.contentWindow ?? null);
      if (reported !== null) {
        setHeight(reported);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: sent anew when the text or the theme changes
  useEffect(() => {
    send();
    const themeChanged = new MutationObserver(send);
    themeChanged.observe(document.documentElement, { attributes: true });
    return () => themeChanged.disconnect();
  }, [html]);

  return (
    <div className={className}>
      <iframe
        // a new policy is a new page: the frame is made anew
        key={src}
        ref={frame}
        src={src}
        sandbox={FRAME_SANDBOX}
        referrerPolicy="no-referrer"
        title="Card text, styled"
        data-frame={images ? "images" : "plain"}
        onLoad={send}
        className="block w-full border-0"
        style={{
          height: Math.min(height ?? FIRST_HEIGHT, max),
          // the same scheme as the framed page's (light, both said outright:
          // the app's meta says "light dark"); otherwise a browser paints the
          // frame opaque instead of clear
          colorScheme: "light",
        }}
      />
    </div>
  );
}

/**
 * The one way a card's pictures load: the viewer asks, for this card, after
 * being told where from.
 */
export function ImagesBar({
  hosts,
  allowed,
  onAllow,
}: {
  hosts: readonly string[];
  allowed: boolean;
  onAllow(): void;
}) {
  if (hosts.length === 0) {
    return null;
  }
  return (
    <div className={cn("flex flex-wrap items-center gap-2 text-sm")}>
      {allowed ? (
        <p className="text-muted-foreground">
          Images from {hosts.join(", ")} are shown for this card.
        </p>
      ) : (
        <>
          <p className="text-muted-foreground">
            This card shows pictures from other sites. They are not loaded until you
            ask.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={onAllow}
            className="h-auto whitespace-normal py-1.5 text-left"
          >
            Load images from {hosts.join(", ")}
          </Button>
        </>
      )}
    </div>
  );
}
