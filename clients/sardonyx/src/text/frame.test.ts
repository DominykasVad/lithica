/**
 * The frame of styled card text, public/frame/card-text.html: its policy
 * names its script by hash, and the script does what it should with what
 * it is sent. The script is run here as served, against a document of its
 * own and a stand-in for the page that embeds it.
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  HEIGHT_MESSAGE,
  heightFrom,
  imageHosts,
  MAX_HEIGHT,
  MIN_HEIGHT,
  needsFrame,
  styledHtml,
  toHtml,
} from "./styled";

const root = path.join(import.meta.dirname, "../..");
const page = readFileSync(path.join(root, "public/frame/card-text.html"), "utf8");
const nginx = readFileSync(path.join(root, "nginx.conf.template"), "utf8");
const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(
  (m) => m[1] ?? "",
);

describe("the frame's policy", () => {
  it("says its colour scheme, the one the page gives the frame (else it is opaque)", () => {
    expect(page).toContain(":root { color-scheme: light; }");
  });

  it("has one inline script and nothing that loads another", () => {
    expect(scripts).toHaveLength(1);
    expect(page).not.toMatch(/<script[^>]*\bsrc=/i);
  });

  it("names that script by its hash, in both policies, and nothing else may run", () => {
    // what a browser hashes: the text between the tags, as UTF-8
    const hash = createHash("sha256")
      .update(scripts[0] ?? "", "utf8")
      .digest("base64");
    const policies = [
      ...nginx.matchAll(
        /map "" \$(frame_csp|frame_images_csp) \{\s*default "([^"]+)";/g,
      ),
    ];
    expect(policies.map((m) => m[1])).toEqual(["frame_csp", "frame_images_csp"]);
    for (const [, name, policy] of policies) {
      const directives = Object.fromEntries(
        (policy ?? "").split(";").map((one) => {
          const [key = "", ...values] = one.trim().split(/\s+/);
          return [key, values.join(" ")];
        }),
      );
      // if this fails after a change of the frame's script: put the new
      // hash into both policies of nginx.conf.template
      expect(directives["script-src"], name).toBe(`'sha256-${hash}'`);
      expect(directives["default-src"]).toBe("'none'");
      expect(directives["style-src"]).toBe("'unsafe-inline'");
      expect(directives["frame-ancestors"]).toBe("'self'");
      expect(directives["connect-src"]).toBeUndefined();
      expect(policy).not.toMatch(/unsafe-eval|unsafe-hashes|form-action|base-uri/);
      expect(directives.sandbox).toBe(
        "allow-scripts allow-popups allow-popups-to-escape-sandbox",
      );
      const images = name === "frame_images_csp";
      expect(directives["img-src"]).toBe(images ? "https: data:" : "data:");
      expect(directives["font-src"]).toBe(images ? "https: data:" : "data:");
    }
  });

  it("is sent with each of the frame's two paths, and the app's own is no weaker", () => {
    expect(nginx).toMatch(
      /location = \/frame\/card-text\.html \{[^}]*Content-Security-Policy \$frame_csp always;/,
    );
    expect(nginx).toMatch(
      /location = \/frame\/card-text-images\.html \{[^}]*Content-Security-Policy \$frame_images_csp always;[^}]*try_files \/frame\/card-text\.html =404;/,
    );
    expect(nginx).toContain(
      `default "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'";`,
    );
  });
});

/** The frame's script, run in a document of its own; what it posted. */
function frame() {
  const document = window.document.implementation.createHTMLDocument("frame");
  const posted: { message: unknown; target: string }[] = [];
  const parent = {
    postMessage: (message: unknown, target: string) => posted.push({ message, target }),
  };
  const listeners: ((event: { source: unknown; data: unknown }) => void)[] = [];
  const frameWindow = {
    parent,
    addEventListener: (_type: string, listener: (typeof listeners)[number]) =>
      listeners.push(listener),
  };
  new Function("window", "document", scripts[0] ?? "")(frameWindow, document);
  const send = (data: unknown, source: unknown = parent) => {
    for (const listener of listeners) {
      listener({ source, data });
    }
  };
  return { document, posted, send, parent };
}

describe("the frame's script", () => {
  it("shows what the page sends, and says how high it is", () => {
    const { document, posted, send } = frame();
    send({ type: "sardonyx-card-text", html: "<p>Hello <b>there</b></p>" });
    expect(document.body.innerHTML).toBe("<p>Hello <b>there</b></p>");
    expect(posted).toEqual([
      { message: { type: "sardonyx-card-text-height", height: 0 }, target: "*" },
    ]);
  });

  it("takes nothing from anyone but the page that embeds it", () => {
    const { document, send } = frame();
    send({ type: "sardonyx-card-text", html: "<p>forged</p>" }, {});
    send({ type: "sardonyx-card-text", html: "<p>forged</p>" }, null);
    send({ type: "other", html: "<p>forged</p>" });
    send({ type: "sardonyx-card-text", html: 42 });
    send("sardonyx-card-text");
    expect(document.body.textContent).not.toContain("forged");
  });

  it("drops what could run, fetch or navigate, and every inline handler", () => {
    const { document, send } = frame();
    send({
      type: "sardonyx-card-text",
      html: `<style>.a{color:red}</style><script>alert(1)</script>
        <meta http-equiv="refresh" content="0;url=https://evil.example/">
        <base href="https://evil.example/"><link rel="dns-prefetch" href="//evil.example">
        <iframe src="https://evil.example/"></iframe><object data="x"></object><embed src="x">
        <img src="x" onerror="alert(2)" onload="alert(3)" alt="pic">
        <div onclick="alert(4)" class="a">kept</div>`,
    });
    const body = document.body;
    expect(
      body.querySelector("script, meta, base, link, iframe, object, embed"),
    ).toBeNull();
    expect(body.innerHTML).not.toMatch(/\son[a-z]+=/i);
    // what is the card's own look is kept
    expect(body.querySelector("style")?.textContent).toBe(".a{color:red}");
    expect(body.querySelector("img")?.getAttribute("alt")).toBe("pic");
    expect(body.querySelector("div.a")?.textContent).toBe("kept");
  });

  it("opens a web link in a new tab, without its opener or referrer; any other is no link", () => {
    const { document, send } = frame();
    send({
      type: "sardonyx-card-text",
      html: `<a href="https://example.com/a" target="_self" rel="opener">web</a>
        <a href=" javascript:alert(1)" target="_top">script</a>
        <a href="data:text/html,x">data</a><a href="/posts/1">relative</a>`,
    });
    const [web, ...others] = [...document.body.querySelectorAll("a")];
    expect(web?.getAttribute("target")).toBe("_blank");
    expect(web?.getAttribute("rel")).toBe("noopener noreferrer nofollow ugc");
    for (const link of others) {
      expect(link.hasAttribute("href")).toBe(false);
      expect(link.hasAttribute("target")).toBe(false);
    }
  });

  it("takes the page's colours, and nothing that would be more than a colour", () => {
    const { document, send } = frame();
    send({
      type: "sardonyx-card-text",
      html: "",
      theme: {
        foreground: "#f6f1ea",
        link: "red; background: url(x)",
        font: "Inter, sans-serif",
      },
    });
    const style = document.documentElement.style;
    expect(style.getPropertyValue("--sx-foreground")).toBe("#f6f1ea");
    expect(style.getPropertyValue("--sx-font")).toBe("Inter, sans-serif");
    expect(style.getPropertyValue("--sx-link")).toBe("");
  });

  it("does nothing when it is not in a frame", () => {
    const document = window.document.implementation.createHTMLDocument("top");
    const self = { addEventListener: vi.fn() } as Record<string, unknown>;
    self.parent = self;
    new Function("window", "document", scripts[0] ?? "")(self, document);
    expect(self.addEventListener).not.toHaveBeenCalled();
  });
});

describe("the page's side", () => {
  const frameWindow = { name: "the frame" } as unknown as Window;
  const message = (data: unknown, source: unknown = frameWindow) =>
    new MessageEvent("message", { data, source: source as Window });

  it("takes a height from the frame only", () => {
    expect(
      heightFrom(message({ type: HEIGHT_MESSAGE, height: 240 }), frameWindow),
    ).toBe(240);
    // another window, or none
    expect(
      heightFrom(message({ type: HEIGHT_MESSAGE, height: 240 }, window), frameWindow),
    ).toBeNull();
    expect(heightFrom(message({ type: HEIGHT_MESSAGE, height: 240 }), null)).toBeNull();
  });

  it("takes nothing but a height that is a number", () => {
    for (const data of [
      { type: HEIGHT_MESSAGE, height: "240" },
      { type: HEIGHT_MESSAGE, height: Number.NaN },
      { type: HEIGHT_MESSAGE, height: Number.POSITIVE_INFINITY },
      { type: HEIGHT_MESSAGE },
      { type: "navigate", height: 240 },
      "240",
      null,
    ]) {
      expect(heightFrom(message(data), frameWindow)).toBeNull();
    }
  });

  it("clamps the height", () => {
    expect(heightFrom(message({ type: HEIGHT_MESSAGE, height: -5 }), frameWindow)).toBe(
      MIN_HEIGHT,
    );
    expect(
      heightFrom(message({ type: HEIGHT_MESSAGE, height: 1e9 }), frameWindow),
    ).toBe(MAX_HEIGHT);
    expect(
      heightFrom(message({ type: HEIGHT_MESSAGE, height: 99.4 }), frameWindow),
    ).toBe(99);
  });
});

describe("the image hosts of a card", () => {
  it("are read from img src, srcset, CSS url() and Markdown pictures, https only, once each", () => {
    expect(
      imageHosts([
        `<img src="https://a.example/1.png"><img src='https://b.example/2.png'>`,
        `<img srcset="https://c.example/s.png 1x, https://d.example/l.png 2x">`,
        `<div style="background: url('https://e.example/bg.jpg')"></div><style>@font-face{src:url(https://f.example/f.woff2)}</style>`,
        `![pic](https://g.example/p.png "title") <img src=https://a.example/again.png>`,
        `<table background="//h.example/t.png">`,
        // not loaded by the frame: not https, or not of another site
        `<img src="http://i.example/x.png"><img src="/data/x.png"><img src="data:image/png;base64,AA">`,
      ]),
    ).toEqual([
      "a.example",
      "b.example",
      "c.example",
      "d.example",
      "e.example",
      "f.example",
      "g.example",
      "h.example",
    ]);
  });

  it("are none for text without pictures", () => {
    expect(imageHosts(["Just *words*, and a [link](https://x.example)."])).toEqual([]);
  });
});

describe("what goes into the frame", () => {
  it("is the Markdown made HTML, the card's HTML as written, macros marked", () => {
    const html = styledHtml(
      '*{{char}}* smiles.\n\n<div class="box" style="color:red">Hi <b>{{user}}</b></div>\n\n![x](https://a.example/x.png)',
    );
    expect(html).toBe(
      '<div class="sx-markdown"><p><em><span class="sx-macro" data-macro="">{{char}}</span></em> smiles.</p>\n<div class="box" style="color:red">Hi <b>{{user}}</b></div>\n<p><img src="https://a.example/x.png" alt="x"></p></div>',
    );
  });

  it("escapes what is text", () => {
    expect(
      toHtml({
        type: "element",
        tagName: "a",
        properties: { href: 'https://x.example/?a=1&b="2"', className: ["one", "two"] },
        children: [{ type: "text", value: "1 < 2 & 3 > 2" }],
      }),
    ).toBe(
      '<a href="https://x.example/?a=1&amp;b=&quot;2&quot;" class="one two">1 &lt; 2 &amp; 3 &gt; 2</a>',
    );
  });

  it("is used for text with HTML or pictures only", () => {
    expect(needsFrame("<div>x</div>")).toBe(true);
    expect(needsFrame("a ![p](https://a.example/p.png)")).toBe(true);
    expect(needsFrame("*just* Markdown, a < b and {{user}}")).toBe(false);
  });
});
