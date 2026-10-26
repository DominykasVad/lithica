import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp } from "@/test-utils";
import { cardSite } from "./fixtures";

const tabs = () => screen.getAllByRole("tab").map((tab) => tab.textContent);

/** The route's own reading of the URL, as the page sees it. */
function searchOf(view: ReturnType<typeof renderApp>) {
  const match = view.router.state.matches.at(-1);
  return (match?.search ?? {}) as Record<string, unknown>;
}

describe("the card viewer", () => {
  it("shows the card: name, creator, version, spec and file; the post's tags once", async () => {
    cardSite();
    renderApp("/posts/5");
    expect(
      await screen.findByRole("heading", { name: "Mira Vell", level: 1 }),
    ).toBeInTheDocument();
    const aside = screen
      .getByRole("heading", { name: "Mira Vell", level: 1 })
      .closest("aside");
    const side = within(aside as HTMLElement);
    expect(side.getByRole("link", { name: "Ann Marie" })).toHaveAttribute(
      "href",
      `/posts?q=${encodeURIComponent("card-creator:Ann*Marie")}`,
    );
    expect(aside).toHaveTextContent("version 1.4");
    const fact = (label: string) =>
      side.getByText(label, { selector: "dt" }).nextElementSibling;
    expect(fact("Spec")).toHaveTextContent("V3");
    expect(fact("File")).toHaveTextContent("CHARX");
    expect(fact("Greetings")).toHaveTextContent("3");
    expect(fact("Lorebook")).toHaveTextContent("25 entries");
    // the card's own tag list is not shown: the post's tags are the one list
    expect(side.queryByText("fantasy")).toBeNull();
    expect(await side.findAllByRole("region", { name: /^Tags/ })).toHaveLength(2);
    expect(side.getAllByRole("link", { name: /coastal/ })).toHaveLength(1);
    expect(
      side.getByRole("button", { name: /Download Mira Vell\.charx/ }),
    ).toBeInTheDocument();
  });

  it("has a tab for each part of the card that has something, and none for an empty one", async () => {
    cardSite();
    renderApp("/posts/5");
    await screen.findByRole("tablist", { name: "Card sections" });
    expect(tabs()).toEqual([
      "Overview",
      "Greetings (3)",
      "Examples",
      "Creator notes",
      "Lorebook (25)",
    ]);
    // the overview leaves out the empty scenario
    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByRole("heading", { name: "Description" }),
    ).toBeInTheDocument();
    expect(within(panel).queryByRole("heading", { name: "Scenario" })).toBeNull();
  });

  it("keeps the tab in the URL, without a history entry", async () => {
    cardSite();
    const view = renderApp("/posts/5?q=sea");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Creator notes" }));
    await waitFor(() =>
      expect(searchOf(view)).toMatchObject({ q: "sea", tab: "notes" }),
    );
    expect(view.router.history.length).toBe(1);
  });

  it("opens at the tab of the URL; one the card has nothing for is the first", async () => {
    cardSite();
    const first = renderApp("/posts/5?tab=examples");
    expect(await screen.findByRole("tab", { name: "Examples" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    first.unmount();
    cardSite();
    renderApp("/posts/5?tab=prompts");
    expect(await screen.findByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("switches greetings, round from the last to the first", async () => {
    cardSite();
    renderApp("/posts/5?tab=greetings");
    const user = userEvent.setup();
    const panel = await screen.findByRole("tabpanel");
    expect(panel).toHaveTextContent("First message");
    expect(panel).toHaveTextContent("1 of 3");
    expect(panel).toHaveTextContent("The lamp is already lit.");
    await user.click(screen.getByRole("button", { name: "Next greeting" }));
    expect(panel).toHaveTextContent("Alternate greeting");
    expect(panel).toHaveTextContent("2 of 3");
    expect(panel).toHaveTextContent("A knock at four in the morning.");
    await user.click(screen.getByRole("button", { name: "Previous greeting" }));
    await user.click(screen.getByRole("button", { name: "Previous greeting" }));
    // the empty alternate greeting is not one
    expect(panel).toHaveTextContent("3 of 3");
    expect(panel).toHaveTextContent("The supply boat is late.");
  });

  it("splits example messages on <START>, shown as written", async () => {
    cardSite();
    renderApp("/posts/5?tab=examples");
    const panel = await screen.findByRole("tabpanel");
    expect(within(panel).getAllByText("<START>")).toHaveLength(2);
    expect(panel.querySelectorAll("[data-text]")).toHaveLength(2);
    expect(panel.querySelector("start")).toBeNull();
    expect(
      [...panel.querySelectorAll("[data-macro]")].map((one) => one.textContent),
    ).toEqual(["{{user}}", "{{char}}", "{{char}}"]);
  });

  it("shows the text of HTML in creator notes, not its markup", async () => {
    cardSite();
    renderApp("/posts/5?tab=notes");
    const panel = await screen.findByRole("tabpanel");
    const notes = panel.querySelector("[data-text]");
    expect(notes?.textContent).toBe("Made for the contest. \nRead me\n");
    expect(panel).not.toHaveTextContent("<div");
    expect(panel.querySelector(".note, [data-text] div")).toBeNull();
  });

  it("shows text as written with Source, and keeps the choice", async () => {
    cardSite();
    const first = renderApp("/posts/5?tab=notes");
    const user = userEvent.setup();
    const panel = await screen.findByRole("tabpanel");
    expect(screen.getByRole("button", { name: "Readable" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Source" }));
    expect(panel.querySelector("[data-text]")?.textContent).toBe(
      'Made for the contest. <div class="note">Read me</div>',
    );
    expect(localStorage.getItem("sardonyx.cardText")).toBe("source");
    first.unmount();

    cardSite();
    renderApp("/posts/5");
    expect(await screen.findByRole("button", { name: "Source" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it.each([
    ["plain", "Source"],
    ["formatted", "Readable"],
    ["something else", "Readable"],
  ])("reads the setting %j, as it was called before, as %s", async (stored, shown) => {
    localStorage.setItem("sardonyx.cardText", stored);
    cardSite();
    renderApp("/posts/5");
    expect(await screen.findByRole("button", { name: shown })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("previews the lorebook: its facts, 20 entries, and the way to all of them", async () => {
    cardSite();
    renderApp("/posts/5?q=sea&tab=lorebook");
    const user = userEvent.setup();
    const panel = await screen.findByRole("tabpanel");
    expect(
      within(panel).getByRole("heading", { name: "The Gullrock Ledger" }),
    ).toBeInTheDocument();
    expect(panel).toHaveTextContent(
      "25 entries · 1 always active · 1 disabled · scan depth 4 · token budget 2048",
    );
    const entries = within(panel).getAllByRole("button", { expanded: false });
    expect(entries).toHaveLength(20);
    await user.click(entries[2] as HTMLElement);
    expect(entries[2]).toHaveAttribute("aria-expanded", "true");
    expect(panel).toHaveTextContent("Content of entry 2.");
    expect(
      within(panel).getByRole("link", {
        name: "Open the full lorebook (25 entries) →",
      }),
    ).toHaveAttribute("href", "/posts/5/lorebook?q=sea");
  });

  it("is not there on a site without cards, and nothing is asked about cards", async () => {
    const sent = cardSite({ modules: [] });
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(sent.some((one) => one.path.startsWith("/modules/"))).toBe(false);
    expect(sent.find((one) => one.path.startsWith("/post/5?"))?.path).not.toMatch(
      /card/,
    );
  });

  it("is not there for a post without a card", async () => {
    const sent = cardSite({ summary: null });
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(sent.some((one) => one.path.startsWith("/modules/"))).toBe(false);
  });

  it("asks for a card once, however often its post is opened", async () => {
    const sent = cardSite();
    const view = renderApp("/posts/5");
    const user = userEvent.setup();
    await screen.findByRole("tablist");
    await user.click(screen.getByRole("tab", { name: "Lorebook (25)" }));
    await user.click(screen.getByRole("link", { name: /Open the full lorebook/ }));
    await screen.findByRole("heading", { name: "The Gullrock Ledger", level: 1 });
    act(() => view.router.history.back());
    await screen.findByRole("tablist");
    expect(
      sent.filter((one) => one.path === "/modules/cards/post/5" && !one.aborted),
    ).toHaveLength(1);
  });
});
