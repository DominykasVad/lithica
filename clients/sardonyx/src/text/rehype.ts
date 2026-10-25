/**
 * The steps that make card text safe to show as Markdown, on the HTML tree
 * react-markdown builds from it (hast). Card text comes from uploaded
 * files: whatever it holds is shown, nothing of it is run or fetched.
 *
 * Before rehype-sanitize:
 * - HTML in the text becomes the text it shows (htmlToText): no markup,
 *   no CSS, line breaks for its blocks. Without this, the sanitiser would
 *   drop it without a trace.
 * - An image is not loaded: it becomes the text `[image: alt]`.
 * - A link shows its URL; only an http(s) one stays a link.
 *
 * After it:
 * - Macros (`{{char}}`, `{{user}}`, any `{{…}}`) are marked to be styled,
 *   their text unchanged.
 */

import { htmlToText } from "./htmlText";

// The few node shapes of hast these steps touch.
interface Text {
  type: "text";
  value: string;
}
interface Raw {
  type: "raw";
  value: string;
}
interface Element {
  type: "element";
  tagName: string;
  properties: Record<string, unknown>;
  children: Node[];
}
type Node = Text | Raw | Element | { type: string; children?: Node[] };
interface Parent {
  children: Node[];
}

function isElement(node: Node): node is Element {
  return node.type === "element";
}

function hasChildren(node: Node): node is Node & Parent {
  return Array.isArray((node as Partial<Parent>).children);
}

/** Replaces each node of the tree with what `change` makes of it. */
function rewrite(parent: Parent, change: (node: Node) => Node[] | null): void {
  parent.children = parent.children.flatMap((node) => {
    const changed = change(node);
    if (changed) {
      return changed;
    }
    if (hasChildren(node)) {
      rewrite(node, change);
    }
    return [node];
  });
}

function textOf(node: Node): string {
  if (node.type === "text" || node.type === "raw") {
    return (node as Text).value;
  }
  return hasChildren(node) ? node.children.map(textOf).join("") : "";
}

const text = (value: string): Text => ({ type: "text", value });

/** An http(s) URL: the only kind a link of card text may open. */
export function isWebUrl(href: string): boolean {
  try {
    const { protocol } = new URL(href);
    return protocol === "http:" || protocol === "https:";
  } catch {
    // relative, or no URL at all
    return false;
  }
}

// a lone tag of a block element, as `<br>` or `</p>` in a paragraph
const BLOCK_TAG = /^<\/?(p|div|br|li|h[1-6]|tr|hr)\b[^>]*>$/i;

/**
 * HTML written in the text, as the text it shows. HTML on lines of its
 * own (an HTML block) becomes a paragraph; a tag within a paragraph, its
 * text, or a line break for a block element's tag.
 */
export function htmlAsText() {
  return (tree: Parent) => {
    // the top level: HTML blocks
    tree.children = tree.children.flatMap((node): Node[] => {
      if (node.type !== "raw") {
        return [node];
      }
      const shown = htmlToText((node as Raw).value);
      return shown
        ? [{ type: "element", tagName: "p", properties: {}, children: [text(shown)] }]
        : [];
    });
    // within paragraphs, lists and the rest: HTML among the text
    rewrite(tree, (node) => {
      if (node.type !== "raw") {
        return null;
      }
      const value = (node as Raw).value.trim();
      return [text(BLOCK_TAG.test(value) ? "\n" : htmlToText(value))];
    });
  };
}

/** An image is named, never loaded. */
export function imagesAsText() {
  return (tree: Parent) =>
    rewrite(tree, (node) => {
      if (!isElement(node) || node.tagName !== "img") {
        return null;
      }
      const alt = String(node.properties.alt ?? "").trim();
      return [text(alt ? `[image: ${alt}]` : "[image]")];
    });
}

/** A link shows where it goes; one that is not http(s) is text only. */
export function linksWithUrl() {
  return (tree: Parent) =>
    rewrite(tree, (node) => {
      if (!isElement(node) || node.tagName !== "a") {
        return null;
      }
      const href = String(node.properties.href ?? "");
      const shown = textOf(node);
      const url = href && href !== shown ? [text(` (${href})`)] : [];
      if (isWebUrl(href)) {
        return [node, ...url];
      }
      return [...node.children, ...url];
    });
}

/** `{{char}}`, `{{user}}` or any other macro, as written. */
const MACRO = /\{\{[^{}]*\}\}/;

export const MACRO_CLASS =
  "rounded-md bg-macro px-1.5 py-px font-mono text-[0.875em] text-macro-foreground";

/** Splits text around its macros: [text, macro, text, macro, …, text]. */
export function splitMacros(value: string): string[] {
  return value.split(/(\{\{[^{}]*\}\})/g);
}

/**
 * Each macro in a span of its own, styled; the text is not changed. The
 * class is the app's (Tailwind) unless the frame's own is asked for.
 */
export function macros(options: { className?: string[] } = {}) {
  const className = options.className ?? MACRO_CLASS.split(" ");
  return (tree: Parent) =>
    rewrite(tree, (node) => {
      if (node.type !== "text" || !MACRO.test((node as Text).value)) {
        return null;
      }
      return splitMacros((node as Text).value)
        .map((piece, i): Node | null => {
          if (!piece) {
            return null;
          }
          return i % 2
            ? {
                type: "element",
                tagName: "span",
                properties: { className, dataMacro: "" },
                children: [text(piece)],
              }
            : text(piece);
        })
        .filter((piece): piece is Node => piece !== null);
    });
}
