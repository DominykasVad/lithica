/**
 * Styled card text (5.4b): the card's HTML and CSS as written, shown in a
 * sandboxed frame (public/frame/card-text.html) and never in the app's
 * page. Here: what goes into the frame, which image hosts a card names,
 * and the one message the page takes from the frame.
 */
import Markdown from "react-markdown";
import { macros } from "./rehype";

/** The frame's page: without images (the default), and with them. */
const BASE = import.meta.env.BASE_URL;
export const FRAME_URL = {
  plain: `${BASE}frame/card-text.html`,
  images: `${BASE}frame/card-text-images.html`,
} as const;

/** Scripts (the frame's own; its policy lets run no other) and new tabs; never the same origin. */
export const FRAME_SANDBOX =
  "allow-scripts allow-popups allow-popups-to-escape-sandbox";

export const CONTENT_MESSAGE = "sardonyx-card-text";
export const HEIGHT_MESSAGE = "sardonyx-card-text-height";

// what the page takes of a frame's height, in CSS pixels
export const MIN_HEIGHT = 16;
export const MAX_HEIGHT = 100_000;

/**
 * The height a frame reports, or null for any other message: one not from
 * that frame's window, of another kind, or without a finite number. Clamped
 * to [MIN_HEIGHT, MAX_HEIGHT].
 */
export function heightFrom(event: MessageEvent, frame: Window | null): number | null {
  if (!frame || event.source !== frame) {
    return null;
  }
  const data: unknown = event.data;
  if (
    typeof data !== "object" ||
    data === null ||
    !("type" in data) ||
    data.type !== HEIGHT_MESSAGE ||
    !("height" in data) ||
    typeof data.height !== "number" ||
    !Number.isFinite(data.height)
  ) {
    return null;
  }
  return Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, Math.round(data.height)));
}

/**
 * Whether Styled shows the text in a frame: when it holds HTML, or Markdown
 * pictures (Readable shows neither). Other text is shown as Readable.
 */
export function needsFrame(text: string): boolean {
  return /<\/?[a-z][^>]*>|!\[[^\]]*\]\(/i.test(text);
}

// where a card names a picture: src=, background=, srcset=, CSS url(),
// Markdown's ![alt](url)
const SOURCES = [
  /\b(?:src|background)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/gi,
  /\burl\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)/gi,
  /!\[[^\]]*\]\(\s*<?([^)\s>]+)/g,
];
const SRCSET = /\bsrcset\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;

function hostOf(url: string): string | null {
  try {
    // a protocol-relative URL as https, the only way it could load
    const parsed = new URL(url.trim().replace(/^\/\//, "https://"));
    return parsed.protocol === "https:" ? parsed.host : null;
  } catch {
    // relative, or no URL: nothing the frame would fetch from another site
    return null;
  }
}

/**
 * The hosts of the pictures and fonts a card's text names, read from the
 * text (nothing is fetched), in their first order. Only https ones: the
 * frame loads nothing else.
 */
export function imageHosts(texts: readonly string[]): string[] {
  const hosts = new Set<string>();
  const add = (url: string | undefined) => {
    const host = url ? hostOf(url) : null;
    if (host) {
      hosts.add(host);
    }
  };
  for (const text of texts) {
    if (!text || !/(src|url\(|background|!\[)/i.test(text)) {
      continue;
    }
    for (const pattern of SOURCES) {
      for (const match of text.matchAll(pattern)) {
        add(match[1] ?? match[2] ?? match[3]);
      }
    }
    for (const match of text.matchAll(SRCSET)) {
      for (const candidate of (match[1] ?? match[2] ?? "").split(",")) {
        add(candidate.trim().split(/\s+/)[0]);
      }
    }
  }
  return [...hosts];
}

// The few hast shapes the serialiser writes.
interface Node {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: Node[];
}

const VOID = new Set([
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "source",
  "track",
  "wbr",
]);

const escapeText = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escapeAttribute = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/"/g, "&quot;");

// hast names properties as the DOM does: className, htmlFor, dataMacro
function attributeName(property: string): string {
  if (property === "className") {
    return "class";
  }
  if (property === "htmlFor") {
    return "for";
  }
  if (/^(data|aria)[A-Z]/.test(property)) {
    return property.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
  }
  return property.toLowerCase();
}

/** HTML of a hast tree; raw HTML of the card as it is written. */
export function toHtml(node: Node): string {
  switch (node.type) {
    case "root":
      return (node.children ?? []).map(toHtml).join("");
    case "text":
      return escapeText(node.value ?? "");
    case "raw":
      return node.value ?? "";
    case "element": {
      const tag = node.tagName ?? "span";
      const attributes = Object.entries(node.properties ?? {})
        .filter(([, value]) => value !== false && value !== null && value !== undefined)
        .map(([property, value]) =>
          value === true
            ? ` ${attributeName(property)}`
            : ` ${attributeName(property)}="${escapeAttribute(
                Array.isArray(value) ? value.join(" ") : String(value),
              )}"`,
        )
        .join("");
      return VOID.has(tag)
        ? `<${tag}${attributes}>`
        : `<${tag}${attributes}>${(node.children ?? []).map(toHtml).join("")}</${tag}>`;
    }
    default:
      // comments, doctypes: nothing to show
      return "";
  }
}

/**
 * The HTML the frame shows for card text: its Markdown made HTML, its own
 * HTML kept as written, macros marked for the frame's style. Built from the
 * tree react-markdown makes, not by rendering it: nothing of it is drawn in
 * the app's page.
 */
export function styledHtml(text: string): string {
  let html = "";
  // calling the component runs its pipeline; the last step writes the tree
  // out there and then, before react-markdown's own last step changes it
  Markdown({
    children: text,
    rehypePlugins: [
      [macros, { className: ["sx-macro"] }],
      () => (root: Node) => {
        html = toHtml(root);
      },
    ],
  });
  return `<div class="sx-markdown">${html}</div>`;
}
