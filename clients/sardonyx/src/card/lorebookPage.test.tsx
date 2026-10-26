import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { renderApp } from "@/test-utils";
import { CARD, cardSite } from "./fixtures";

// jsdom lays nothing out: an entry is as high as a browser draws a closed
// one, an open one higher. What the list measures its rows by.
const CLOSED = 58;
const OPEN = 240;
const offsetHeight = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "offsetHeight",
);

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get(this: HTMLElement) {
      if (!this.hasAttribute("data-index")) {
        return 0;
      }
      return this.querySelector("[aria-expanded=true]") ? OPEN : CLOSED;
    },
  });
});

afterEach(() => {
  if (offsetHeight) {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", offsetHeight);
  }
});

/** A lorebook of `count` entries: every 10th always active, every 7th off. */
function bigCard(count: number) {
  return {
    ...CARD,
    lorebook: {
      ...CARD.lorebook,
      entries: Array.from({ length: count }, (_, i) => ({
        keys: [`key${i}`, i % 3 ? "forest" : "harbour"],
        secondaryKeys: i % 5 === 0 ? ["night"] : [],
        content: `Entry ${i} tells of the ${i % 2 ? "Dragon" : "lamp"}.`,
        enabled: i % 7 !== 0,
        order: i,
        name: i % 4 ? `Name ${i}` : "",
        comment: i % 4 ? "" : `Comment ${i}`,
        constant: i % 10 === 0,
        selective: true,
        caseSensitive: i === 2 ? true : null,
        useRegex: null,
        position: i === 2 ? "before_char" : null,
        priority: null,
        id: i,
        extensions: {},
      })),
    },
  };
}

const rows = () =>
  screen.getByTestId("lorebook-entries").querySelectorAll("[data-entry]");
const kindButton = (label: RegExp) => screen.getByRole("button", { name: label });

function searchOf(view: ReturnType<typeof renderApp>) {
  return (view.router.state.matches.at(-1)?.search ?? {}) as Record<string, unknown>;
}

describe("the lorebook page", () => {
  it("says what the lorebook is, and draws only the entries on screen", async () => {
    cardSite({ card: bigCard(2500) });
    renderApp("/posts/5/lorebook?q=sea");
    expect(
      await screen.findByRole("heading", { name: "The Gullrock Ledger", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent(
      /Lorebook of Mira Vell · 2,500 entries · [\d,]+ characters · scan depth 4 · token budget 2048/,
    );
    expect(screen.getByText("Showing 2,500 of 2,500 entries")).toBeInTheDocument();
    await waitFor(() => expect(rows().length).toBeGreaterThan(0));
    // a 768 px window holds 14 rows of 58 px; a few more are drawn ahead
    expect(rows().length).toBeLessThan(30);
    expect(screen.getByTestId("lorebook-entries").style.height).toBe(
      `${2500 * CLOSED}px`,
    );
    // the way back: to the post, and the library, keeping the search
    const crumbs = within(screen.getByRole("navigation", { name: "Breadcrumb" }));
    expect(crumbs.getByRole("link", { name: "Mira Vell" })).toHaveAttribute(
      "href",
      "/posts/5?q=sea",
    );
    expect(crumbs.getByRole("link", { name: "Library" })).toHaveAttribute(
      "href",
      "/posts?q=sea",
    );
  });

  it("names an entry by its name, else its comment, else its first key", async () => {
    cardSite({ card: bigCard(30) });
    renderApp("/posts/5/lorebook");
    await waitFor(() => expect(rows().length).toBeGreaterThan(4));
    const [first, second] = [...rows()] as [HTMLElement, HTMLElement];
    expect(first).toHaveTextContent("Comment 0");
    expect(second).toHaveTextContent("Name 1");
    expect(second).toHaveTextContent("key1");
    expect(second).toHaveTextContent("forest");
    expect(second).toHaveTextContent("keyword");
    expect(second).toHaveTextContent("enabled");
    // entry 0: always active, and off
    expect(first).toHaveTextContent("always active");
    expect(within(first).getByText("disabled")).toHaveClass("text-warn");
    expect(within(second).getByText("enabled")).toHaveClass("text-ok");
  });

  it("finds entries by key, name, comment or content, whatever the case, with counts per kind", async () => {
    cardSite({ card: bigCard(2500) });
    const view = renderApp("/posts/5/lorebook");
    const user = userEvent.setup();
    const field = await screen.findByRole("searchbox", { name: /Filter entries/ });
    // before: the kinds of every entry
    expect(kindButton(/^All /)).toHaveTextContent("All 2,500");
    expect(kindButton(/^Always active /)).toHaveTextContent("Always active 250");
    expect(kindButton(/^Disabled /)).toHaveTextContent("Disabled 358");
    expect(kindButton(/^Selective /)).toHaveTextContent("Selective 250");

    await user.type(field, "DRAGON");
    await waitFor(() =>
      expect(screen.getByText("Showing 1,250 of 2,500 entries")).toBeInTheDocument(),
    );
    expect(kindButton(/^All /)).toHaveTextContent("All 1,250");
    expect(kindButton(/^Always active /)).toHaveTextContent("Always active 0");
    // by a key, and by a comment
    await user.clear(field);
    await user.type(field, "harbour");
    await waitFor(() =>
      expect(screen.getByText(/^Showing 834 of/)).toBeInTheDocument(),
    );
    await user.clear(field);
    await user.type(field, "comment 12");
    await waitFor(() => expect(screen.getByText(/^Showing 29 of/)).toBeInTheDocument());
    // the URL says it once typing rests, without history entries
    await waitFor(() => expect(searchOf(view).filter).toBe("comment 12"));
    expect(view.router.history.length).toBe(1);
  });

  it("shows one kind at a time, in the URL", async () => {
    cardSite({ card: bigCard(100) });
    const view = renderApp("/posts/5/lorebook");
    const user = userEvent.setup();
    await screen.findByRole("searchbox", { name: /Filter entries/ });
    await user.click(kindButton(/^Disabled /));
    await waitFor(() => expect(searchOf(view).kind).toBe("disabled"));
    expect(kindButton(/^Disabled /)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Showing 15 of 100 entries")).toBeInTheDocument();
    for (const row of rows()) {
      expect(row).toHaveTextContent("disabled");
    }
    await user.click(kindButton(/^All /));
    await waitFor(() => expect(searchOf(view).kind).toBeUndefined());
    expect(view.router.history.length).toBe(1);
  });

  it("opens with the filter and kind of the URL", async () => {
    cardSite({ card: bigCard(100) });
    renderApp("/posts/5/lorebook?filter=lamp&kind=constant");
    expect(
      await screen.findByRole("searchbox", { name: /Filter entries/ }),
    ).toHaveValue("lamp");
    expect(kindButton(/^Always active /)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Showing 10 of 100 entries")).toBeInTheDocument();
  });

  it("says when no entry matches", async () => {
    cardSite({ card: bigCard(10) });
    renderApp("/posts/5/lorebook?filter=nowhere");
    expect(
      await screen.findByText("No entry matches this filter."),
    ).toBeInTheDocument();
  });

  it("opens and closes an entry: its content and the details it sets", async () => {
    cardSite({ card: bigCard(30) });
    renderApp("/posts/5/lorebook");
    const user = userEvent.setup();
    await waitFor(() => expect(rows().length).toBeGreaterThan(4));
    const third = () =>
      screen
        .getByTestId("lorebook-entries")
        .querySelector("[data-entry='2']") as HTMLElement;
    const toggle = within(third()).getByRole("button");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(third()).toHaveTextContent("Entry 2 tells of the lamp.");
    expect(third()).toHaveTextContent("Order:2");
    expect(third()).toHaveTextContent("Position:before_char");
    expect(third()).toHaveTextContent("Case sensitive:yes");
    expect(third()).toHaveTextContent("Id:2");
    // what the card does not set is not listed
    expect(third()).not.toHaveTextContent("Priority");
    expect(third()).not.toHaveTextContent("Regex");
    // the list makes room for it: measured anew
    await waitFor(() =>
      expect(screen.getByTestId("lorebook-entries").style.height).toBe(
        `${29 * CLOSED + OPEN}px`,
      ),
    );
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(third()).not.toHaveTextContent("Entry 2 tells of the lamp.");
  });

  it("draws other entries as the window scrolls", async () => {
    cardSite({ card: bigCard(2500) });
    renderApp("/posts/5/lorebook");
    await waitFor(() => expect(rows().length).toBeGreaterThan(0));
    await act(async () => {
      window.scrollTo({ top: 2000 * CLOSED });
    });
    await waitFor(() =>
      expect(
        screen.getByTestId("lorebook-entries").querySelector("[data-entry='2000']"),
      ).not.toBeNull(),
    );
    expect(rows().length).toBeLessThan(30);
  });
});
