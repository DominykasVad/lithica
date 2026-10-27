import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { cardSite } from "@/card/fixtures";
import { CATEGORIES, POST } from "@/post/fixtures";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

/** A library of four posts; 2 and 3 are NSFW. */
function library() {
  return fakeSite({
    "GET /info": { body: { ...INFO, modules: [] } },
    "GET /posts": {
      body: {
        query: "",
        offset: 0,
        limit: 100,
        total: 4,
        results: [1, 2, 3, 4].map((id) => ({
          id,
          type: "image",
          thumbnailUrl: `data/generated-thumbnails/${id}.jpg`,
          nsfw: id === 2 || id === 3,
        })),
      },
    },
  } as never);
}

const results = () => within(screen.getByRole("region", { name: "Results" }));

/** The tile of a post: what holds its link. */
function tile(id: number): HTMLElement {
  const link = results()
    .getAllByRole("link")
    .find((one) => one.getAttribute("href")?.split("?")[0] === `/posts/${id}`);
  if (!link?.parentElement) {
    throw new Error(`no tile of post ${id}`);
  }
  return link.parentElement;
}

const blurred = (element: HTMLElement) =>
  element.querySelector("img")?.className.includes("blur") ?? false;

async function tilesShown() {
  await waitFor(() => expect(results().getAllByRole("link")).toHaveLength(4));
}

describe("NSFW posts in the library", () => {
  it("are blurred with a label while Show NSFW is off, as it is by default", async () => {
    library();
    renderApp("/posts");
    await tilesShown();
    for (const id of [2, 3]) {
      expect(blurred(tile(id))).toBe(true);
      expect(within(tile(id)).getByText("NSFW")).toBeInTheDocument();
    }
    for (const id of [1, 4]) {
      expect(blurred(tile(id))).toBe(false);
      expect(within(tile(id)).queryByText("NSFW")).toBeNull();
    }
  });

  it("are revealed one at a time by a click, which opens nothing", async () => {
    library();
    const view = renderApp("/posts");
    await tilesShown();
    const user = userEvent.setup();
    await user.click(within(tile(2)).getByRole("button", { name: "Show this post" }));
    expect(blurred(tile(2))).toBe(false);
    expect(within(tile(2)).queryByText("NSFW")).toBeNull();
    // the other stays hidden, and the library stays where it is
    expect(blurred(tile(3))).toBe(true);
    expect(view.router.state.location.pathname).toBe("/posts");
  });

  it("stay revealed for the tab's session, and only those", async () => {
    library();
    const first = renderApp("/posts");
    await tilesShown();
    await userEvent
      .setup()
      .click(within(tile(3)).getByRole("button", { name: "Show this post" }));
    first.unmount();

    library();
    renderApp("/posts");
    await tilesShown();
    expect(blurred(tile(3))).toBe(false);
    expect(blurred(tile(2))).toBe(true);
  });

  it("are shown as any post with Show NSFW on, kept per browser", async () => {
    library();
    const first = renderApp("/posts");
    await tilesShown();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Display" }));
    await user.click(
      await screen.findByRole("menuitemcheckbox", { name: "Show NSFW" }),
    );
    expect(blurred(tile(2))).toBe(false);
    expect(blurred(tile(3))).toBe(false);
    expect(localStorage.getItem("sardonyx.showNsfw")).toBe("true");
    first.unmount();

    library();
    renderApp("/posts");
    await tilesShown();
    expect(blurred(tile(2))).toBe(false);

    // and off again
    await user.click(screen.getByRole("button", { name: "Display" }));
    const item = await screen.findByRole("menuitemcheckbox", { name: "Show NSFW" });
    expect(item).toHaveAttribute("aria-checked", "true");
    await user.click(item);
    expect(blurred(tile(2))).toBe(true);
    expect(localStorage.getItem("sardonyx.showNsfw")).toBeNull();
  });

  it("are blurred when the browser refuses storage", async () => {
    localStorage.setItem("sardonyx.showNsfw", "true");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    library();
    renderApp("/posts");
    await tilesShown();
    expect(blurred(tile(2))).toBe(true);
  });
});

describe("a NSFW post's page", () => {
  function site() {
    return fakeSite({
      "GET /info": { body: { ...INFO, modules: [] } },
      "GET /post/5": { body: { ...POST, nsfw: true } },
      "GET /post/5/around": { body: { prev: null, next: null } },
      "GET /tag-categories": { body: CATEGORIES },
    } as never);
  }

  it("asks whether the post is NSFW", async () => {
    const sent = site();
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    const asked = sent.find((one: Sent) => one.path.startsWith("/post/5?"))?.path;
    expect(
      new URLSearchParams(asked?.split("?")[1]).get("fields")?.split(","),
    ).toContain("nsfw");
  });

  it("shows its thumbnail blurred, not its file, until revealed", async () => {
    site();
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    const main = within(screen.getByRole("main"));
    const picture = () => screen.getByRole("main").querySelector("img");
    expect(picture()).toHaveAttribute(
      "src",
      expect.stringMatching(/\/data\/generated-thumbnails\/5_abc\.jpg$/),
    );
    expect(picture()?.className).toContain("blur");
    expect(main.getByText("NSFW")).toBeInTheDocument();

    await userEvent.setup().click(main.getByRole("button", { name: "Show this post" }));
    expect(picture()).toHaveAttribute(
      "src",
      expect.stringMatching(/\/data\/posts\/5_abc\.png$/),
    );
    expect(picture()?.className).not.toContain("blur");
  });

  it("keeps a card's text behind the same click", async () => {
    cardSite({ post: { nsfw: true } });
    renderApp("/posts/5");
    const hidden = await screen.findByRole("region", { name: "Card text hidden" });
    expect(screen.queryByRole("tablist", { name: "Card sections" })).toBeNull();
    // the card's own name and facts are the post's header, not its text
    expect(screen.getByRole("heading", { name: "Mira Vell" })).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(within(hidden).getByRole("button", { name: "Show this post" }));
    expect(
      await screen.findByRole("tablist", { name: "Card sections" }),
    ).toBeInTheDocument();
    // one click for the post: its picture is revealed with its text
    expect(screen.queryByText("NSFW")).toBeNull();
  });

  it("hides the lorebook of a NSFW card too, until revealed", async () => {
    cardSite({ post: { nsfw: true } });
    renderApp("/posts/5/lorebook");
    const hidden = await screen.findByRole("region", { name: "Card text hidden" });
    expect(screen.queryByRole("searchbox")).toBeNull();
    await userEvent
      .setup()
      .click(within(hidden).getByRole("button", { name: "Show this post" }));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Card text hidden" })).toBeNull(),
    );
  });
});
