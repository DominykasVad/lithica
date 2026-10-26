/**
 * The text of HTML written in card text, for reading: its tags left out,
 * what `<style>`, `<script>` and the like hold dropped, block elements as
 * line breaks, entities decoded. Plain string work: the HTML is never
 * parsed by the browser, so nothing of it is drawn, run or fetched.
 */

// elements whose content is not text to read
const DROPPED = [
  "style",
  "script",
  "template",
  "noscript",
  "textarea",
  "title",
  "head",
];

// elements that start a line of their own
const BLOCKS = new Set([
  "p",
  "div",
  "br",
  "li",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "tr",
  "ul",
  "ol",
  "table",
  "section",
  "article",
  "header",
  "footer",
  "blockquote",
  "pre",
  "hr",
  "figure",
  "figcaption",
  "details",
  "summary",
]);

const NAMED: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  hellip: "…",
  mdash: "—",
  ndash: "–",
  lsquo: "‘",
  rsquo: "’",
  ldquo: "“",
  rdquo: "”",
  laquo: "«",
  raquo: "»",
  bull: "•",
  middot: "·",
  times: "×",
  deg: "°",
  copy: "©",
  reg: "®",
  trade: "™",
  euro: "€",
  hearts: "♥",
  star: "☆",
};

/** `&amp;`, `&#39;`, `&#x2764;` and the common named ones; others as written. */
export function decodeEntities(text: string): string {
  return text.replace(
    /&(#x[0-9a-f]+|#\d+|[a-z][a-z0-9]*);/gi,
    (whole, name: string) => {
      if (name[0] === "#") {
        const code =
          name[1] === "x" || name[1] === "X"
            ? Number.parseInt(name.slice(2), 16)
            : Number.parseInt(name.slice(1), 10);
        // a code point there is, and not a control character
        return code > 0x1f && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff)
          ? String.fromCodePoint(code)
          : whole;
      }
      return NAMED[name.toLowerCase()] ?? whole;
    },
  );
}

// `<style …>…</style>`, to the end of the text when it is never closed
const DROPPED_CONTENT = new RegExp(
  `<(${DROPPED.join("|")})\\b[^>]*>[\\s\\S]*?(?:<\\/\\1\\s*>|$)`,
  "gi",
);
const COMMENT = /<!--[\s\S]*?(?:-->|$)/g;
// a tag: its name, and anything up to its end, quoted values with `>` in them
const TAG = /<\/?([a-z][a-z0-9-]*)\b(?:[^>"']|"[^"]*"|'[^']*')*>/gi;
const DECLARATION = /<![^>]*>|<\?[^>]*>/g;

/** The readable text of HTML: lines, no markup. */
export function htmlToText(html: string): string {
  const text = html
    .replace(COMMENT, "")
    .replace(DROPPED_CONTENT, "")
    .replace(DECLARATION, "")
    // whitespace in HTML is a space, whatever it is; lines come from blocks
    .replace(/\s+/g, " ")
    .replace(TAG, (_tag, name: string) => (BLOCKS.has(name.toLowerCase()) ? "\n" : ""));
  return (
    decodeEntities(text)
      .split("\n")
      .map((line) => line.replace(/[ \t]+/g, " ").trim())
      .join("\n")
      // the end of one block and the start of the next are one line break
      .replace(/\n{2,}/g, "\n")
      .trim()
  );
}
