import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CardText, examples, TextModeProvider } from "./CardText";
import { decodeEntities, htmlToText } from "./htmlText";

function readable(text: string) {
  return render(<CardText text={text} />).container;
}

function source(text: string) {
  return render(
    <TextModeProvider mode="source">
      <CardText text={text} />
    </TextModeProvider>,
  ).container;
}

// What the creator notes of a card from Chub look like: a style sheet and
// nested blocks with classes, an image, entities.
const STYLED_NOTES = `<div class="am-wrap"><style>.am-wrap{max-width:1100px;background:linear-gradient(135deg,#120d10,#1b1216)}
.am-title{font-size:17px}</style>
<div class="am-hero"><img src="https://files.example/hero.png" alt="Amelia"></div>
<div class="am-section"><div class="am-title">About   Amelia</div>
<div class="am-text">Bookstore manager &amp; writer &mdash; she loves &quot;slow&quot; mornings.<br>Second line&nbsp;here.</div></div>
<ul><li>Coffee</li><li>Books &#x2764;</li></ul><script>alert(1)</script></div>`;

describe("card text, readable", () => {
  it("is Markdown", () => {
    const shown = readable("*She smiles.* **Loudly.**\n\n- one\n- two");
    expect(shown.querySelector("em")).toHaveTextContent("She smiles.");
    expect(shown.querySelector("strong")).toHaveTextContent("Loudly.");
    expect(shown.querySelectorAll("li")).toHaveLength(2);
  });

  it("shows the text of HTML, not its markup: no CSS, no script, blocks as lines", () => {
    const shown = readable(STYLED_NOTES);
    const block = shown.querySelector("[data-text=readable]") as HTMLElement;
    const lines = (block.textContent ?? "").split("\n").filter(Boolean);
    expect(lines).toEqual([
      "About Amelia",
      'Bookstore manager & writer — she loves "slow" mornings.',
      "Second line\u00a0here.",
      "Coffee",
      "Books ❤",
    ]);
    // nothing of the markup, the style sheet or the script is left
    for (const gone of ["<", "am-wrap", "{", "max-width", "alert"]) {
      expect(block.textContent).not.toContain(gone);
    }
    // nor drawn: no element of the card's, and no image
    expect(block.querySelector("div, style, script, img, ul")).toBeNull();
  });

  it("keeps HTML among Markdown as text, a block tag as a line break", () => {
    const shown = readable(
      'Before <span class="x" onclick="alert(1)">inside</span> after<br>next\n\n<script>\nalert(2)\n\nmore()\n</script>\n\n*still Markdown*',
    );
    const paragraphs = [...shown.querySelectorAll("[data-text] p")].map(
      (p) => p.textContent,
    );
    expect(paragraphs).toEqual(["Before inside after\nnext", "still Markdown"]);
    expect(shown.querySelector("em")).toHaveTextContent("still Markdown");
    expect(
      shown.querySelector("[data-text] span:not([data-macro]), [data-text] br"),
    ).toBeNull();
  });

  it("does not load images: it names them", () => {
    const shown = readable(
      "![a red door](https://example.com/door.png) and ![](https://example.com/x.png)",
    );
    expect(shown.querySelector("img")).toBeNull();
    expect(shown).toHaveTextContent("[image: a red door] and [image]");
    expect(shown.innerHTML).not.toContain("example.com");
  });

  it("links only to http(s), opening apart, and shows where a link goes", () => {
    const shown = readable(
      "[the wiki](https://example.com/wiki) [mail](mailto:a@b.c) [run](javascript:alert(1)) [here](/posts/1) <https://example.org>",
    );
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "https://example.com/wiki",
      "https://example.org",
    ]);
    for (const link of links) {
      expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow ugc");
      expect(link).toHaveAttribute("target", "_blank");
    }
    expect(shown).toHaveTextContent(
      "the wiki (https://example.com/wiki) mail (mailto:a@b.c) run (javascript:alert(1)) here (/posts/1) https://example.org",
    );
  });

  it("styles macros as written, also inside Markdown, and replaces none", () => {
    const shown = readable("{{char}} looks at *{{user}}*.\n\n- {{random:a,b}}");
    const styled = [...shown.querySelectorAll("[data-macro]")];
    expect(styled.map((one) => one.textContent)).toEqual([
      "{{char}}",
      "{{user}}",
      "{{random:a,b}}",
    ]);
    expect(styled[1]?.closest("em")).not.toBeNull();
    expect(shown).toHaveTextContent("{{char}} looks at {{user}}.");
  });
});

describe("card text, source", () => {
  it("is the source, every character of it, macros styled", () => {
    const written =
      "  *Not italic*\n\n<div>kept</div>  ![x](https://example.com/x.png)\n{{char}}\ttab";
    const shown = source(written);
    const block = shown.querySelector("[data-text=source]");
    expect(block?.textContent).toBe(written);
    expect(block).toHaveClass("whitespace-pre-wrap");
    expect(block).not.toHaveClass("font-mono");
    expect(block?.querySelector("em, img, div")).toBeNull();
    expect(shown.querySelector("[data-macro]")).toHaveTextContent("{{char}}");
  });
});

describe("card text, source, with HTML", () => {
  it("keeps the markup exactly as written", () => {
    const shown = source(STYLED_NOTES);
    expect(shown.querySelector("[data-text=source]")?.textContent).toBe(STYLED_NOTES);
    expect(shown.querySelector("[data-text] div, img, style, script")).toBeNull();
  });
});

describe("the text of HTML", () => {
  it("drops what style, script and comments hold, even unclosed", () => {
    expect(
      htmlToText("a<style>p{color:red}</style>b<!-- note -->c<script>x()</script>d"),
    ).toBe("abcd");
    expect(htmlToText("kept<style>never closed {")).toBe("kept");
    expect(htmlToText("<STYLE type='text/css'>x</STYLE >y")).toBe("y");
  });

  it("makes block elements lines and leaves inline ones out", () => {
    expect(
      htmlToText(
        "<h1>Title</h1><p>One <b>bold</b> word</p><div>Two</div>three<br/>four",
      ),
    ).toBe("Title\nOne bold word\nTwo\nthree\nfour");
    expect(
      htmlToText("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>"),
    ).toBe("ab\nc");
    // whitespace in HTML is a space; empty blocks make no empty lines
    expect(htmlToText("<p>  a \n  b </p>\n\n<div></div><div></div><p>c</p>")).toBe(
      "a b\nc",
    );
  });

  it("reads a quoted > in an attribute as part of the tag", () => {
    expect(htmlToText('<a title="1 > 0" href="x">link</a>')).toBe("link");
  });

  it("decodes entities, and leaves what is no entity as written", () => {
    expect(
      decodeEntities("&lt;b&gt; &amp;amp; &#39;&#x41;&hellip; &unknown; & &#0;"),
    ).toBe("<b> &amp; 'A… &unknown; & &#0;");
  });
});

describe("example messages", () => {
  it("are split on their <START> lines", () => {
    expect(
      examples(
        "<START>\n{{user}}: hi\n{{char}}: hello\n<START>\n  <start>  \n\nsecond",
      ),
    ).toEqual(["{{user}}: hi\n{{char}}: hello", "second"]);
    expect(examples("no marker")).toEqual(["no marker"]);
    // a <START> inside a line is not a split
    expect(examples("a <START> b")).toEqual(["a <START> b"]);
  });
});
