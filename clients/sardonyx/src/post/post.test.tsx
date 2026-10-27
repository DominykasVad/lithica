import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCredentials } from "@/api/client";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";
import { BLOB_URL_LIFETIME, download, fallbackName, fileNameOf } from "./download";
import { CATEGORIES, POST } from "./fixtures";

const TOKEN = "f5a2c0de-0000-4000-8000-000000000001";

/** A site with post 5, its neighbours in "sea", and anything else asked. */
function site(routes: Record<string, unknown> = {}, modules = ["cards"]) {
  return fakeSite({
    "GET /info": { body: { ...INFO, modules } },
    "GET /post/5": { body: POST },
    "GET /post/5/around": (sent: Sent) =>
      sent.path.includes("query=sea")
        ? { body: { prev: { id: 6 }, next: { id: 4 } } }
        : { body: { prev: null, next: null } },
    "GET /post/4": { body: { ...POST, id: 4 } },
    "GET /post/4/around": { body: { prev: { id: 5 }, next: null } },
    "GET /post/6": { body: { ...POST, id: 6 } },
    "GET /post/6/around": { body: { prev: null, next: { id: 5 } } },
    "GET /tag-categories": { body: CATEGORIES },
    ...routes,
  } as never);
}

const main = () => screen.getByRole("main");

describe("the post page", () => {
  it("asks for what it shows, the card only on a site with cards", async () => {
    const sent = site();
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    const asked = sent.find((one) => one.path.startsWith("/post/5?"))?.path ?? "";
    const fields = new URLSearchParams(asked.split("?")[1]).get("fields")?.split(",");
    expect(fields).toEqual(
      expect.arrayContaining(["id", "safety", "source", "tags", "contentUrl", "card"]),
    );
  });

  it("shows the facts of the post", async () => {
    site();
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    const facts = within(main());
    const fact = (label: string) =>
      facts.getByText(label, { selector: "dt" }).nextElementSibling;
    expect(fact("Safety")).toHaveTextContent("sketchy");
    expect(fact("File size")).toHaveTextContent("1.5 MB");
    expect(fact("Dimensions")).toHaveTextContent("800 × 1200");
    expect(fact("Uploaded by")).toHaveTextContent("ashwyn");
    expect(fact("Uploaded")).toHaveTextContent("Oct 20, 2026");
    expect(fact("Last edited")).toHaveTextContent("Oct 21, 2026");
    // the picture, from the site
    expect(main().querySelector("img")).toHaveAttribute(
      "src",
      expect.stringMatching(/\/data\/posts\/5_abc\.png$/),
    );
  });

  it("links a source only when it is a web address", async () => {
    site();
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    const source = within(
      within(main()).getByText("Source", { selector: "dt" })
        .nextElementSibling as HTMLElement,
    );
    const link = source.getByRole("link");
    expect(link).toHaveAttribute("href", "https://example.com/art/5");
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow ugc");
    expect(source.getAllByRole("link")).toHaveLength(1);
    expect(source.getByText("Book of the coast, page 3").tagName).toBe("LI");
    expect(source.getByText("javascript:alert(1)").tagName).toBe("LI");
  });

  it("groups the tags by category, in the categories' order, each a search", async () => {
    site();
    renderApp("/posts/5");
    const groups = await screen.findAllByRole("region", { name: /^Tags/ });
    expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
      "Tags",
      "Tags: character",
    ]);
    const [general, character] = groups as [HTMLElement, HTMLElement];
    // the default category goes without a heading; the others have theirs
    expect(within(general).queryByRole("heading")).toBeNull();
    expect(
      within(character).getByRole("heading", { name: "character" }),
    ).toBeInTheDocument();
    // the category's own colour; "default" is none
    expect(character.querySelector("[data-color]")).toHaveAttribute(
      "data-color",
      "#aa3366",
    );
    expect(general.querySelector("[data-color]")).toBeNull();
    expect(within(character).getByRole("link", { name: /mira_vell/ })).toHaveAttribute(
      "href",
      "/posts?q=mira_vell",
    );
    // the tag written as a query: what the engine reads specially is escaped
    expect(within(general).getByRole("link", { name: /a:b/ })).toHaveAttribute(
      "href",
      `/posts?q=${encodeURIComponent("a\\:b")}`,
    );
  });

  it("goes back to the library at the search and place it came from", async () => {
    site();
    const view = renderApp("/posts/5?q=sea&at=100");
    const back = await screen.findByRole("link", { name: "Back to library" });
    expect(back).toHaveAttribute("href", "/posts?q=sea&at=100");
    await userEvent.setup().click(back);
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/posts"));
  });

  it("links the previous and next post of the search, and the arrow keys go there", async () => {
    const sent = site();
    const view = renderApp("/posts/5?q=sea&at=100");
    const previous = await screen.findByRole("link", { name: "Previous" });
    expect(previous).toHaveAttribute("href", "/posts/6?q=sea&at=100");
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/posts/4?q=sea&at=100",
    );
    expect(sent.map((one) => one.path)).toContain("/post/5/around?query=sea&fields=id");

    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/posts/4"));
    expect(view.router.state.location.searchStr).toBe("?q=sea&at=100");
    await screen.findByRole("link", { name: "Previous" });
    fireEvent.keyDown(document.body, { key: "ArrowLeft" });
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/posts/5"));
  });

  it("leaves the arrow keys to a text field, and to keys with a modifier", async () => {
    site();
    const view = renderApp("/posts/5?q=sea");
    await screen.findByRole("link", { name: "Next" });
    const field = document.createElement("input");
    document.body.append(field);
    field.focus();
    fireEvent.keyDown(field, { key: "ArrowRight" });
    fireEvent.keyDown(document.body, { key: "ArrowRight", altKey: true });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(view.router.state.location.pathname).toBe("/posts/5");
    field.remove();
  });

  it("shows no previous or next without neighbours", async () => {
    site();
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("link", { name: "Previous" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Next" })).toBeNull();
  });

  it("shows a picture at full size on a click, and back", async () => {
    site();
    renderApp("/posts/5");
    const user = userEvent.setup();
    const picture = await screen.findByRole("button", {
      name: "Show the picture at full size",
    });
    await user.click(picture);
    expect(
      screen.getByRole("button", { name: "Fit the picture to the page" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("plays a video with the browser's controls, and shows a CHARX file's thumbnail", async () => {
    site({
      "GET /post/7": {
        body: { ...POST, id: 7, type: "video", contentUrl: "data/posts/7.mp4" },
      },
      "GET /post/8": {
        body: { ...POST, id: 8, type: "charx", contentUrl: "data/posts/8.charx" },
      },
    });
    const first = renderApp("/posts/7");
    await screen.findByRole("heading", { name: "Post 7" });
    const video = main().querySelector("video");
    expect(video).toHaveAttribute("controls");
    expect(video?.getAttribute("src")).toMatch(/\/data\/posts\/7\.mp4$/);
    first.unmount();

    renderApp("/posts/8");
    await screen.findByRole("heading", { name: "Post 8" });
    expect(main().querySelector("img")?.getAttribute("src")).toMatch(
      /\/data\/generated-thumbnails\/5_abc\.jpg$/,
    );
  });

  it("shows a post that is not there as such, with the way back", async () => {
    fakeSite({
      "GET /info": { body: INFO },
      "GET /post/99": {
        status: 404,
        body: {
          name: "PostNotFoundError",
          title: "Not found",
          description: "Post 99 not found.",
        },
      },
    });
    renderApp("/posts/99?q=sea");
    expect(await screen.findByRole("alert")).toHaveTextContent("Post 99 not found.");
    expect(screen.getByRole("heading", { name: "Post 99" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to library" })).toHaveAttribute(
      "href",
      "/posts?q=sea",
    );
  });
});

describe("downloading", () => {
  let saved: { name: string; blob: Blob | null }[];
  let blobs: Map<string, Blob>;

  beforeEach(() => {
    saved = [];
    blobs = new Map();
    // what jsdom does not have: the URL of a blob, and saving a file
    URL.createObjectURL = vi.fn((blob: Blob) => {
      const url = `blob:test/${blobs.size}`;
      blobs.set(url, blob);
      return url;
    });
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved.push({ name: this.download, blob: blobs.get(this.href) ?? null });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("saves the original under the name the site gives, asked with the session", async () => {
    sessionStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: TOKEN }),
    );
    const bytes = new Uint8Array([137, 80, 78, 71, 1, 2, 3]);
    const sent = site({
      "GET /data/posts/5_abc.png": {
        body: null,
        raw: bytes,
        headers: {
          "Content-Disposition": "attachment; filename*=UTF-8''sea%20wall.png",
        },
      },
    });
    renderApp("/posts/5");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: /Download the original/ }),
    );
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]?.name).toBe("sea wall.png");
    expect(new Uint8Array((await saved[0]?.blob?.arrayBuffer()) ?? [])).toEqual(bytes);
    const request = sent.find((one) => one.path === "/data/posts/5_abc.png");
    expect(request?.authorization).toMatch(/^Token /);
  });

  it("falls back to the post's number and its file's extension", async () => {
    site({
      "GET /data/posts/5_abc.png": { body: null, raw: new Uint8Array([1]) },
    });
    renderApp("/posts/5");
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: /Download the original/ }));
    await waitFor(() => expect(saved[0]?.name).toBe("5.png"));
  });

  it("sends the token to this site only, never to another host", async () => {
    setCredentials({ user: "ada", token: TOKEN });
    const asked: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) => {
        asked.push(request);
        return new Response(new Uint8Array([1]));
      }),
    );
    try {
      await download(`${window.location.origin}/data/posts/5.png`, "5.png");
      await download("data/posts/6.png", "6.png");
      await download("https://files.example.com/posts/7.png", "7.png");
      await download("//files.example.com/posts/8.png", "8.png");
    } finally {
      vi.unstubAllGlobals();
      setCredentials(null);
    }
    expect(asked.map((request) => request.headers.get("Authorization"))).toEqual([
      expect.stringMatching(/^Token /),
      expect.stringMatching(/^Token /),
      null,
      null,
    ]);
    expect(saved.map((one) => one.name)).toEqual(["5.png", "6.png", "7.png", "8.png"]);
  });

  it("keeps the file's blob URL for a minute after the click", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(new Uint8Array([1]))),
    );
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    try {
      await download("data/posts/5.png", "5.png");
      expect(saved).toHaveLength(1);
      vi.advanceTimersByTime(BLOB_URL_LIFETIME - 1);
      expect(URL.revokeObjectURL).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test/0");
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
    expect(BLOB_URL_LIFETIME).toBe(60_000);
  });

  it("shows why a download failed", async () => {
    site({
      "GET /data/posts/5_abc.png": {
        status: 403,
        body: {
          name: "AuthError",
          title: "Not allowed",
          description: "Insufficient privileges to view this post.",
        },
      },
    });
    renderApp("/posts/5");
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: /Download the original/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Insufficient privileges to view this post.",
    );
    expect(saved).toHaveLength(0);
  });
});

describe("the file name of a download", () => {
  it("is read from Content-Disposition, filename* first", () => {
    expect(fileNameOf('attachment; filename="Mira Vell.charx"')).toBe(
      "Mira Vell.charx",
    );
    expect(fileNameOf("attachment; filename=plain.png")).toBe("plain.png");
    expect(
      fileNameOf(
        "attachment; filename=\"Mira.png\"; filename*=UTF-8''Mir%C3%A1%20V.png",
      ),
    ).toBe("Mirá V.png");
    expect(fileNameOf('attachment; filename="a \\"b\\".png"')).toBe('a "b".png');
    // a name, never a path
    expect(fileNameOf('attachment; filename="../../etc/passwd"')).toBe("passwd");
    expect(fileNameOf("attachment")).toBeNull();
    expect(fileNameOf(null)).toBeNull();
  });

  it("falls back to the post's number and extension", () => {
    expect(fallbackName(5, "data/posts/5_abc.charx")).toBe("5.charx");
    expect(fallbackName(5, "data/posts/5_abc.png?x=1")).toBe("5.png");
    expect(fallbackName(5, undefined)).toBe("5");
  });
});
