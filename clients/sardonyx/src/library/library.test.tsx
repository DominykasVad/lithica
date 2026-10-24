import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

// What the tests' window gives the list: 1024 px wide (five columns of
// 180 px tiles with 20 px between), 768 px high; a row is 332 px.
const ROW = 332;
const COLUMNS = 5;

function params(sent: Sent): URLSearchParams {
  return new URLSearchParams(sent.path.split("?")[1] ?? "");
}

interface SiteOptions {
  total?: number;
  cards?: boolean;
  /** answer this request for posts with an error */
  fails?: (offset: number, sent: Sent) => boolean;
  tags?: (query: string) => string[] | Promise<string[]>;
}

/** A site with `total` posts; with cards, each odd one is a card. */
function library({ total = 1000, cards = true, fails, tags }: SiteOptions = {}) {
  return fakeSite({
    "GET /info": { body: cards ? INFO : { ...INFO, modules: [] } },
    "GET /posts": (sent: Sent) => {
      const asked = params(sent);
      const offset = Number(asked.get("offset") ?? 0);
      const limit = Number(asked.get("limit") ?? 100);
      if (fails?.(offset, sent)) {
        return {
          status: 503,
          body: { name: "HttpError", title: "Busy", description: "Try later." },
        };
      }
      const withCard = (asked.get("fields") ?? "").split(",").includes("card");
      const results = [];
      for (let i = offset; i < Math.min(total, offset + limit); i++) {
        results.push({
          id: i + 1,
          type: "image",
          thumbnailUrl: `data/generated-thumbnails/${i + 1}.jpg`,
          ...(withCard
            ? {
                card:
                  i % 2
                    ? {
                        name: `Card ${i + 1}`,
                        creator: "ashwyn",
                        spec: "v2",
                        format: "png",
                        greetingCount: 3,
                        lorebookEntryCount: 42,
                      }
                    : null,
              }
            : {}),
        });
      }
      return {
        body: { query: asked.get("query") ?? "", offset, limit, total, results },
      };
    },
    "GET /tags": async (sent: Sent) => {
      const query = params(sent).get("query") ?? "";
      const names = (await tags?.(query)) ?? [];
      return {
        body: {
          query,
          offset: 0,
          limit: 10,
          total: names.length,
          results: names.map((name, i) => ({
            names: [name],
            category: "default",
            usages: 100 - i,
          })),
        },
      };
    },
  } as never);
}

// the requests the app kept: not those it let go of
const postRequests = (sent: Sent[]) =>
  sent.filter(
    (one) => one.method === "GET" && one.path.startsWith("/posts?") && !one.aborted,
  );

const offsetsAsked = (sent: Sent[]) =>
  postRequests(sent).map((one) => Number(params(one).get("offset")));

/** The library's search as its route reads it from the URL. */
function search(view: ReturnType<typeof renderApp>) {
  const match = view.router.state.matches.find((one) => one.routeId === "/posts");
  return (match?.search ?? {}) as { q?: string; at?: number };
}

function tiles() {
  return within(screen.getByRole("region", { name: "Results" }))
    .queryAllByRole("link")
    .filter((link) => link.getAttribute("href")?.startsWith("/posts/"));
}

async function scrollTo(top: number) {
  await act(async () => {
    window.scrollTo({ top });
  });
}

function pageMode(size: 50 | 100) {
  localStorage.setItem("sardonyx.perPage", String(size));
}

describe("the library", () => {
  it("is in the header, at /posts", async () => {
    library();
    const view = renderApp("/");
    const user = userEvent.setup();
    await user.click(
      within(await screen.findByRole("navigation", { name: "Main" })).getByRole(
        "link",
        {
          name: "Library",
        },
      ),
    );
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/posts"));
    expect(await screen.findByRole("search")).toBeInTheDocument();
  });

  it("asks only for what a tile shows, the card where there are cards", async () => {
    const sent = library();
    renderApp("/posts");
    await waitFor(() => expect(postRequests(sent)).toHaveLength(1));
    expect(params(postRequests(sent)[0] as Sent).get("fields")).toBe(
      "id,type,thumbnailUrl,card",
    );
  });

  it("on a site without cards: no filters and no card field", async () => {
    const sent = library({ cards: false });
    renderApp("/posts");
    await waitFor(() => expect(tiles().length).toBeGreaterThan(0));
    expect(params(postRequests(sent)[0] as Sent).get("fields")).toBe(
      "id,type,thumbnailUrl",
    );
    expect(screen.queryByRole("complementary", { name: "Card filters" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Filters/ })).toBeNull();
    // a tile without a card: the post's number and its type
    expect(tiles()[0]).toHaveTextContent("IMAGE");
    expect(tiles()[0]).toHaveTextContent("Post 1");
  });

  it("shows a card's summary on its tile, and the post without one", async () => {
    library({ total: 4 });
    renderApp("/posts");
    await waitFor(() => expect(tiles()).toHaveLength(4));
    const [plain, card] = tiles();
    expect(plain).toHaveTextContent("Post 1");
    expect(plain).toHaveAttribute("href", "/posts/1");
    expect(card).toHaveTextContent("Card 2");
    expect(card).toHaveTextContent("by ashwyn");
    expect(card).toHaveTextContent("3 greetings · lorebook 42");
    expect(card).toHaveTextContent("PNG");
    const picture = card?.querySelector("img");
    expect(picture).toHaveAttribute("loading", "lazy");
    expect(picture).toHaveAttribute("width", "180");
    expect(picture).toHaveAttribute("height", "240");
    expect(picture?.getAttribute("src")).toBe(
      new URL("/data/generated-thumbnails/2.jpg", document.baseURI).href,
    );
  });

  it("says so when nothing is found, with the query", async () => {
    library({ total: 0 });
    renderApp("/posts?q=nothing");
    expect(await screen.findByText(/Nothing found for/)).toHaveTextContent(
      "Nothing found for nothing.",
    );
  });

  it("reads an at that is not a whole number above 0 as the start", async () => {
    for (const at of ["-5", "abc", "1.5"]) {
      const sent = library();
      const view = renderApp(`/posts?at=${at}`);
      await waitFor(() => expect(postRequests(sent)).toHaveLength(1));
      expect(offsetsAsked(sent)).toEqual([0]);
      expect(search(view).at).toBeUndefined();
      view.unmount();
    }
  });

  it("makes a new search a new page of history, and back goes to the one before", async () => {
    pageMode(50);
    library();
    const view = renderApp("/posts?q=sea&at=100");
    const user = userEvent.setup();
    const box = await screen.findByRole("combobox", { name: "Search query" });
    expect(box).toHaveValue("sea");
    await user.clear(box);
    await user.type(box, "coast{Enter}");
    await waitFor(() => expect(search(view)).toEqual({ q: "coast" }));
    act(() => view.router.history.back());
    await waitFor(() => expect(search(view)).toEqual({ q: "sea", at: 100 }));
    expect(box).toHaveValue("sea");
  });
});

describe("the per page setting", () => {
  it("is auto load unless this browser chose otherwise", async () => {
    const sent = library();
    renderApp("/posts");
    await waitFor(() => expect(postRequests(sent)).toHaveLength(1));
    expect(params(postRequests(sent)[0] as Sent).get("limit")).toBe("100");
    expect(screen.getByLabelText("Per page")).toHaveValue("auto");
  });

  it("is kept per browser", async () => {
    library();
    const view = renderApp("/posts");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Per page"), "50");
    expect(localStorage.getItem("sardonyx.perPage")).toBe("50");
    view.unmount();

    const sent = library();
    renderApp("/posts");
    await waitFor(() => expect(postRequests(sent)).toHaveLength(1));
    expect(params(postRequests(sent)[0] as Sent).get("limit")).toBe("50");
  });

  it("falls back to auto load when storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    const sent = library();
    renderApp("/posts");
    await waitFor(() => expect(postRequests(sent)).toHaveLength(1));
    expect(params(postRequests(sent)[0] as Sent).get("limit")).toBe("100");
  });

  it("keeps the place when the mode changes", async () => {
    pageMode(50);
    const sent = library();
    const view = renderApp("/posts?at=150");
    const user = userEvent.setup();
    await waitFor(() => expect(tiles().length).toBe(50));
    // to auto load: at stays, and the list opens there
    await user.selectOptions(screen.getByLabelText("Per page"), "auto");
    await waitFor(() => expect(offsetsAsked(sent).at(-1)).toBe(100));
    await waitFor(() => expect(window.scrollY).toBe((150 / COLUMNS) * ROW));
    expect(search(view).at).toBe(150);
    // to pages of 100: the page that holds it
    await user.selectOptions(screen.getByLabelText("Per page"), "100");
    await waitFor(() => expect(search(view).at).toBe(100));
    expect(offsetsAsked(sent).at(-1)).toBe(100);
  });
});

describe("page mode", () => {
  it("asks for a page of the chosen size, from the page that holds at", async () => {
    pageMode(50);
    const sent = library();
    const view = renderApp("/posts?at=120");
    await waitFor(() => expect(tiles()).toHaveLength(50));
    const [asked] = postRequests(sent);
    expect(params(asked as Sent).get("offset")).toBe("100");
    expect(params(asked as Sent).get("limit")).toBe("50");
    // the URL says which page it is
    expect(search(view).at).toBe(100);
    expect(tiles()[0]).toHaveAttribute("href", "/posts/101");
  });

  it("pages with a history entry each, from the top, and back returns", async () => {
    pageMode(100);
    const sent = library({ total: 1000 });
    const view = renderApp("/posts?at=300");
    const user = userEvent.setup();
    const pages = await screen.findByRole("navigation", { name: "Pages" });
    // numbered around the current one, and first, previous, next, last
    expect(within(pages).getByRole("link", { name: "Page 4" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    for (const name of ["Page 2", "Page 6", "First page", "Last page"]) {
      expect(within(pages).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(pages).queryByRole("link", { name: "Page 7" })).toBeNull();

    await scrollTo(900);
    await user.click(within(pages).getByRole("link", { name: "Next page" }));
    await waitFor(() => expect(search(view).at).toBe(400));
    await waitFor(() => expect(offsetsAsked(sent).at(-1)).toBe(400));
    await waitFor(() => expect(window.scrollY).toBe(0));

    await user.click(screen.getByRole("link", { name: "Last page" }));
    await waitFor(() => expect(search(view).at).toBe(900));

    act(() => view.router.history.back());
    await waitFor(() => expect(search(view).at).toBe(400));
    act(() => view.router.history.back());
    await waitFor(() => expect(search(view).at).toBe(300));
  });

  it("shows a page past the end as such, with a way to the first", async () => {
    pageMode(50);
    library({ total: 120 });
    const view = renderApp("/posts?q=sea&at=5000");
    const user = userEvent.setup();
    expect(
      await screen.findByText("This page is past the end of the results."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Go to the first page" }));
    await waitFor(() => expect(search(view)).toEqual({ q: "sea" }));
    await waitFor(() => expect(tiles()).toHaveLength(50));
  });

  it("shows a failure, and asks again", async () => {
    pageMode(50);
    let failing = true;
    library({ fails: () => failing });
    renderApp("/posts");
    const user = userEvent.setup();
    expect(await screen.findByRole("alert")).toHaveTextContent("Try later.");
    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(tiles()).toHaveLength(50));
  });
});

describe("auto load", () => {
  it("loads batches of 100 as they are scrolled to, drawing only the rows in view", async () => {
    const sent = library({ total: 1000 });
    renderApp("/posts");
    await waitFor(() => expect(tiles().length).toBeGreaterThan(0));
    expect(offsetsAsked(sent)).toEqual([0]);
    // three rows fill the window, two more are drawn ahead: 25 of 100
    expect(tiles()).toHaveLength(5 * COLUMNS);
    expect(screen.getByText("1 of 1000")).toBeInTheDocument();

    await scrollTo(18 * ROW);
    await waitFor(() => expect(offsetsAsked(sent)).toEqual([0, 100]));
    await waitFor(() =>
      expect(tiles().map((tile) => tile.getAttribute("href"))).toContain("/posts/101"),
    );
    expect(tiles().length).toBeLessThanOrEqual(7 * COLUMNS);
    expect(screen.getByText(`${18 * COLUMNS + 1} of 1000`)).toBeInTheDocument();
  });

  it("opens at `at`: that batch first, scrolled to; earlier ones when scrolled up to", async () => {
    const sent = library({ total: 1000 });
    renderApp("/posts?at=250");
    await waitFor(() => expect(window.scrollY).toBe((250 / COLUMNS) * ROW));
    expect(offsetsAsked(sent)[0]).toBe(200);
    await waitFor(() =>
      expect(tiles().map((tile) => tile.getAttribute("href"))).toContain("/posts/251"),
    );
    expect(offsetsAsked(sent)).toEqual([200]);

    await scrollTo(30 * ROW);
    await waitFor(() => expect(offsetsAsked(sent)).toEqual([200, 100]));
  });

  it("writes the place into the URL without a history entry", async () => {
    library({ total: 1000 });
    const view = renderApp("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("link", { name: "Library" }));
    await waitFor(() => expect(tiles().length).toBeGreaterThan(0));

    await scrollTo(10 * ROW);
    await waitFor(() => expect(search(view).at).toBe(10 * COLUMNS));
    await scrollTo(12 * ROW);
    await waitFor(() => expect(search(view).at).toBe(12 * COLUMNS));
    // back leaves the library: scrolling made no entries of its own
    act(() => view.router.history.back());
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/"));
  });

  it("keeps the loaded rows when a batch fails, and asks for it again", async () => {
    let failing = true;
    const sent = library({ total: 1000, fails: (offset) => offset === 100 && failing });
    renderApp("/posts");
    const user = userEvent.setup();
    await waitFor(() => expect(tiles().length).toBeGreaterThan(0));

    await scrollTo(17 * ROW);
    expect(await screen.findByRole("alert")).toHaveTextContent("Try later.");
    const hrefs = () => tiles().map((tile) => tile.getAttribute("href"));
    // the rows of the first batch are still there
    expect(hrefs()).toContain("/posts/96");
    expect(hrefs()).not.toContain("/posts/101");

    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(hrefs()).toContain("/posts/101"));
    expect(hrefs()).toContain("/posts/96");
    expect(offsetsAsked(sent)).toEqual([0, 100, 100]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("goes back to the top", async () => {
    library({ total: 1000 });
    renderApp("/posts?at=500");
    const user = userEvent.setup();
    await waitFor(() => expect(window.scrollY).toBeGreaterThan(0));
    await user.click(screen.getByRole("button", { name: "Back to top" }));
    await waitFor(() => expect(window.scrollY).toBe(0));
  });

  it("comes back to the same place from a post", async () => {
    library({ total: 1000 });
    const view = renderApp("/posts?at=250");
    const user = userEvent.setup();
    await waitFor(() =>
      expect(tiles().map((tile) => tile.getAttribute("href"))).toContain("/posts/251"),
    );
    const tile = tiles().find((one) => one.getAttribute("href") === "/posts/251");
    await user.click(tile as HTMLElement);
    expect(
      await screen.findByRole("heading", { name: "Post 251" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(search(view).at).toBe(250));
    await waitFor(() => expect(window.scrollY).toBe((250 / COLUMNS) * ROW));
  });
});

// the tags the site has for a completion query
const tagsFor = (query: string) =>
  query.startsWith("co*") ? ["coastal", "cozy", "cobalt"] : ["nsfw"];

describe("tag completion", () => {
  async function typeInto(text: string) {
    const user = userEvent.setup();
    const box = await screen.findByRole("combobox", { name: "Search query" });
    await user.type(box, text);
    return { user, box };
  }

  it("asks for the most used tags that start with the token, with the fields shown", async () => {
    const sent = library({ tags: tagsFor });
    renderApp("/posts");
    await typeInto("sea co");
    const listbox = await screen.findByRole("listbox", { name: "Tags" });
    expect(
      within(listbox)
        .getAllByRole("option")
        .map((one) => one.textContent),
    ).toEqual(["coastaldefault100", "cozydefault99", "cobaltdefault98"]);
    const asked = sent.filter((one) => one.path.startsWith("/tags?") && !one.aborted);
    // the debounce: one request for what was typed last
    expect(asked).toHaveLength(1);
    expect(params(asked[0] as Sent).get("query")).toBe("co* sort:usages");
    expect(params(asked[0] as Sent).get("limit")).toBe("10");
    expect(params(asked[0] as Sent).get("fields")).toBe("names,category,usages");
  });

  it("takes a tag with the keys, replacing only that token", async () => {
    library({ tags: tagsFor });
    const view = renderApp("/posts");
    const { user, box } = await typeInto("sea co");
    await screen.findByRole("listbox", { name: "Tags" });
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(box).toHaveAttribute(
      "aria-activedescendant",
      screen.getAllByRole("option")[1]?.id,
    );
    await user.keyboard("{Enter}");
    expect(box).toHaveValue("sea cozy ");
    expect(screen.queryByRole("listbox", { name: "Tags" })).toBeNull();
    // taking a tag is not searching
    expect(search(view).q).toBeUndefined();

    // Tab takes too, in the middle of the text, and keeps a negation
    await user.clear(box);
    await user.type(box, "-ns sort:id");
    await user.keyboard("{ArrowLeft>8}");
    await user.type(box, "f", { initialSelectionStart: 3, initialSelectionEnd: 3 });
    await screen.findByRole("listbox", { name: "Tags" });
    await user.keyboard("{ArrowDown}{Tab}");
    expect(box).toHaveValue("-nsfw sort:id");
  });

  it("takes a tag with the mouse, and closes with Escape", async () => {
    library({ tags: tagsFor });
    renderApp("/posts");
    const { user, box } = await typeInto("co");
    await user.click(await screen.findByRole("option", { name: /cobalt/ }));
    expect(box).toHaveValue("cobalt ");
    await user.type(box, "co");
    await screen.findByRole("listbox", { name: "Tags" });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox", { name: "Tags" })).toBeNull();
    expect(box).toHaveValue("cobalt co");
  });

  it("leaves named tokens alone", async () => {
    const sent = library({ tags: tagsFor });
    renderApp("/posts");
    await typeInto("sort:co");
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(sent.filter((one) => one.path.startsWith("/tags?"))).toEqual([]);
  });

  it("does not show the answer for a token as it was before", async () => {
    let slow: (names: string[]) => void = () => {};
    const sent = library({
      tags: (query) =>
        query.startsWith("co*")
          ? new Promise<string[]>((resolve) => {
              slow = resolve;
            })
          : ["coastal"],
    });
    renderApp("/posts");
    const { user } = await typeInto("co");
    await waitFor(() =>
      expect(
        sent.filter((one) => one.path.startsWith("/tags?") && !one.aborted),
      ).toHaveLength(1),
    );
    await user.type(screen.getByRole("combobox", { name: "Search query" }), "a");
    expect(await screen.findByRole("option", { name: /coastal/ })).toBeInTheDocument();
    // the answer for "co" comes late, and is not shown
    act(() => slow(["cobalt"]));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("option", { name: /cobalt/ })).toBeNull();
  });
});

describe("card filters", () => {
  it("fold away behind a button below md, which counts them", async () => {
    library();
    renderApp(`/posts?q=${encodeURIComponent("sea card-spec:v2 card-greetings:2..4")}`);
    const user = userEvent.setup();
    const panel = await screen.findByRole("complementary", { name: "Card filters" });
    // one set and one custom: both filter
    const button = screen.getByRole("button", { name: "Filters (2)" });
    expect(button).toHaveAttribute("aria-controls", panel.id);
    expect(button).toHaveAttribute("aria-expanded", "false");
    // hidden by the stylesheet below md, a side panel from md on
    expect(panel).toHaveClass("max-md:hidden");
    expect(button).toHaveClass("md:hidden");

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(panel).not.toHaveClass("max-md:hidden");
    await user.click(button);
    expect(panel).toHaveClass("max-md:hidden");
  });

  it("are counted as typed, and the button says none when there are none", async () => {
    library();
    renderApp("/posts?q=sea");
    const user = userEvent.setup();
    expect(await screen.findByRole("button", { name: "Filters" })).toBeInTheDocument();
    await user.type(
      screen.getByRole("combobox", { name: "Search query" }),
      " card-format:png",
    );
    expect(screen.getByRole("button", { name: "Filters (1)" })).toBeInTheDocument();
  });

  it("are read from the query text, custom where they cannot show it", async () => {
    library();
    renderApp(
      `/posts?q=${encodeURIComponent("sea card-spec:v2,v3 card-greetings:2..4 card-lorebook:yes")}`,
    );
    const panel = await screen.findByRole("complementary", { name: "Card filters" });
    expect(within(panel).getByRole("checkbox", { name: "V2" })).toBeChecked();
    expect(within(panel).getByRole("checkbox", { name: "V1" })).not.toBeChecked();
    expect(within(panel).getByRole("radio", { name: "With lorebook" })).toBeChecked();
    const greetings = within(panel).getByLabelText(/Greetings, at least/);
    expect(greetings).toHaveValue(null);
    expect(greetings.closest("div")).toHaveTextContent("custom");
  });

  it("write into the query text, as a new search from the start", async () => {
    library();
    const view = renderApp(`/posts?q=${encodeURIComponent("sea  -nsfw")}&at=300`);
    const user = userEvent.setup();
    const panel = await screen.findByRole("complementary", { name: "Card filters" });
    await user.click(within(panel).getByRole("checkbox", { name: "CHARX" }));
    await waitFor(() =>
      expect(search(view)).toEqual({ q: "sea  -nsfw card-format:charx" }),
    );
    expect(screen.getByRole("combobox", { name: "Search query" })).toHaveValue(
      "sea  -nsfw card-format:charx",
    );

    await user.type(within(panel).getByLabelText("Creator"), "Ann Marie{Enter}");
    await waitFor(() =>
      expect(search(view).q).toBe(
        "sea  -nsfw card-format:charx card-creator:Ann*Marie",
      ),
    );
    await user.click(within(panel).getByRole("radio", { name: "Without" }));
    await waitFor(() => expect(search(view).q).toMatch(/card-lorebook:no$/));
    const greetings = within(panel).getByLabelText(/Greetings, at least/);
    await user.type(greetings, "2");
    fireEvent.blur(greetings);
    await waitFor(() => expect(search(view).q).toMatch(/card-greetings:2\.\.$/));

    // and one taken back off: only its token goes
    await user.click(within(panel).getByRole("checkbox", { name: "CHARX" }));
    await waitFor(() =>
      expect(search(view).q).toBe(
        "sea  -nsfw card-creator:Ann*Marie card-lorebook:no card-greetings:2..",
      ),
    );
  });
});
