import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CardText, examples, TextModeProvider } from "./CardText";

function formatted(text: string) {
  return render(<CardText text={text} />).container;
}

function plain(text: string) {
  return render(
    <TextModeProvider mode="plain">
      <CardText text={text} />
    </TextModeProvider>,
  ).container;
}

describe("card text, formatted", () => {
  it("is Markdown", () => {
    const shown = formatted("*She smiles.* **Loudly.**\n\n- one\n- two");
    expect(shown.querySelector("em")).toHaveTextContent("She smiles.");
    expect(shown.querySelector("strong")).toHaveTextContent("Loudly.");
    expect(shown.querySelectorAll("li")).toHaveLength(2);
  });

  it("shows HTML as the text it is: not drawn, not dropped", () => {
    const shown = formatted(
      'Before <div class="x" onclick="alert(1)">inside</div> after<br>next\n\n<script>alert(2)</script>\n\n<START>',
    );
    expect(shown).toHaveTextContent('<div class="x" onclick="alert(1)">');
    expect(shown).toHaveTextContent("</div>");
    expect(shown).toHaveTextContent("<br>");
    expect(shown).toHaveTextContent("<script>alert(2)</script>");
    expect(shown).toHaveTextContent("<START>");
    for (const tag of ["div", "br", "script", "start"]) {
      expect(shown.querySelector(`[data-text] ${tag}`)).toBeNull();
    }
  });

  it("does not load images: it names them", () => {
    const shown = formatted(
      "![a red door](https://example.com/door.png) and ![](https://example.com/x.png)",
    );
    expect(shown.querySelector("img")).toBeNull();
    expect(shown).toHaveTextContent("[image: a red door] and [image]");
    expect(shown.innerHTML).not.toContain("example.com");
  });

  it("links only to http(s), opening apart, and shows where a link goes", () => {
    const shown = formatted(
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
    const shown = formatted("{{char}} looks at *{{user}}*.\n\n- {{random:a,b}}");
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

describe("card text, plain", () => {
  it("is the source, every character of it, macros styled", () => {
    const source =
      "  *Not italic*\n\n<div>kept</div>  ![x](https://example.com/x.png)\n{{char}}\ttab";
    const shown = plain(source);
    const block = shown.querySelector("[data-text=plain]");
    expect(block?.textContent).toBe(source);
    expect(block).toHaveClass("whitespace-pre-wrap");
    expect(block).not.toHaveClass("font-mono");
    expect(block?.querySelector("em, img, div")).toBeNull();
    expect(shown.querySelector("[data-macro]")).toHaveTextContent("{{char}}");
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
