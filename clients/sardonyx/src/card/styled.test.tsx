import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CATEGORIES, POST } from "@/post/fixtures";
import { fakeSite, INFO, renderApp } from "@/test-utils";
import { FRAME_SANDBOX, HEIGHT_MESSAGE } from "@/text/styled";
import { CARD } from "./fixtures";

const NOTES =
  '<div class="sx-test-notes"><style>.sx-test-notes{color:red}</style><b>Made</b> with <img src="https://cdn.example/banner.png"></div>';

/** Two card posts: 5 with styled notes and pictures, 6 with another picture. */
function site() {
  const card = (id: number, extra: Record<string, unknown>) => ({
    ...CARD,
    postId: id,
    ...extra,
  });
  const summary = {
    name: "Mira",
    creator: null,
    spec: "v3",
    format: "png",
    greetingCount: 1,
    lorebookEntryCount: 0,
  };
  return fakeSite({
    "GET /info": { body: INFO },
    "GET /post/5": { body: { ...POST, card: summary } },
    "GET /post/6": { body: { ...POST, id: 6, card: summary } },
    "GET /post/5/around": { body: { prev: null, next: { id: 6 } } },
    "GET /post/6/around": { body: { prev: { id: 5 }, next: null } },
    "GET /tag-categories": { body: CATEGORIES },
    "GET /modules/cards/post/5": {
      body: card(5, {
        creatorNotes: NOTES,
        alternateGreetings: ["Look: ![sea](https://img.example/sea.jpg)"],
        lorebook: null,
      }),
    },
    "GET /modules/cards/post/6": {
      body: card(6, {
        creatorNotes: '<img src="https://other.example/x.png">',
        lorebook: null,
      }),
    },
  } as never);
}

const frames = () => [...document.querySelectorAll("iframe")];

async function styled(path = "/posts/5?tab=notes") {
  localStorage.setItem("sardonyx.cardText", "styled");
  const sent = site();
  const view = renderApp(path);
  await screen.findByRole("tabpanel");
  await waitFor(() => expect(frames().length).toBeGreaterThan(0));
  return { sent, view };
}

describe("styled card text", () => {
  it("is a third mode, kept per browser", async () => {
    site();
    renderApp("/posts/5");
    const user = userEvent.setup();
    const modes = within(await screen.findByRole("group", { name: "Card text" }));
    expect(modes.getAllByRole("button").map((one) => one.textContent)).toEqual([
      "Readable",
      "Styled",
      "Source",
    ]);
    await user.click(modes.getByRole("button", { name: "Styled" }));
    expect(localStorage.getItem("sardonyx.cardText")).toBe("styled");
    expect(modes.getByRole("button", { name: "Styled" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows HTML in a sandboxed frame, never in the page", async () => {
    await styled();
    const [frame] = frames();
    expect(frame?.getAttribute("sandbox")).toBe(FRAME_SANDBOX);
    expect(FRAME_SANDBOX).toBe(
      "allow-scripts allow-popups allow-popups-to-escape-sandbox",
    );
    expect(frame?.getAttribute("src")).toBe("/frame/card-text.html");
    expect(frame?.getAttribute("referrerpolicy")).toBe("no-referrer");
    // the scheme the framed page says too: a frame of another is painted opaque
    expect(frame?.style.colorScheme).toBe("light");
    // nothing of the card's HTML is in the app's own document
    expect(
      document.querySelector(".sx-test-notes, img[src*='cdn.example']"),
    ).toBeNull();
  });

  it("sends the card's HTML to the frame when it has loaded", async () => {
    await styled();
    const [frame] = frames() as [HTMLIFrameElement];
    const post = vi.spyOn(frame.contentWindow as Window, "postMessage");
    fireEvent.load(frame);
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "sardonyx-card-text",
        html: expect.stringContaining(NOTES),
      }),
      "*",
    );
  });

  it("takes the height the frame reports, up to most of the window, and no other's", async () => {
    await styled();
    const [frame] = frames() as [HTMLIFrameElement];
    const report = (height: unknown, source: unknown = frame.contentWindow) =>
      act(() => {
        window.dispatchEvent(
          new MessageEvent("message", {
            data: { type: HEIGHT_MESSAGE, height },
            source: source as Window,
          }),
        );
      });
    report(300);
    expect(frame.style.height).toBe("300px");
    // another window's message, or not a number: nothing changes
    report(50, window);
    report("50");
    expect(frame.style.height).toBe("300px");
    // 80% of the 768 px window at most; the frame scrolls inside
    report(5000);
    expect(frame.style.height).toBe(`${Math.round(768 * 0.8)}px`);
  });

  it("shows text without HTML or pictures as Readable, without a frame", async () => {
    localStorage.setItem("sardonyx.cardText", "styled");
    site();
    renderApp("/posts/5?tab=overview");
    const panel = await screen.findByRole("tabpanel");
    await waitFor(() => expect(panel.querySelector("iframe")).toBeNull());
    expect(panel.querySelector("em")).toHaveTextContent("Gullrock");
  });

  it("loads a card's pictures only when asked, from the hosts it names, for that card only", async () => {
    const { view } = await styled();
    const user = userEvent.setup();
    const ask = screen.getByRole("button", {
      name: "Load images from img.example, cdn.example",
    });
    expect(
      frames().every((one) => one.getAttribute("src") === "/frame/card-text.html"),
    ).toBe(true);

    await user.click(ask);
    await waitFor(() =>
      expect(frames().map((one) => one.getAttribute("src"))).toEqual([
        "/frame/card-text-images.html",
      ]),
    );
    expect(
      screen.getByText("Images from img.example, cdn.example are shown for this card."),
    ).toBeInTheDocument();
    // the greetings of the same card too
    await user.click(screen.getByRole("tab", { name: /Greetings/ }));
    await user.click(await screen.findByRole("button", { name: "Next greeting" }));
    await waitFor(() =>
      expect(frames().map((one) => one.getAttribute("src"))).toEqual([
        "/frame/card-text-images.html",
      ]),
    );

    // another card starts without
    await user.click(screen.getByRole("link", { name: "Next" }));
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/posts/6"));
    expect(
      await screen.findByRole("button", { name: "Load images from other.example" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Creator notes" }));
    await waitFor(() =>
      expect(frames().map((one) => one.getAttribute("src"))).toEqual([
        "/frame/card-text.html",
      ]),
    );
  });

  it("does not change Readable or Source: no frame, no offer of pictures", async () => {
    for (const mode of ["readable", "source"]) {
      localStorage.setItem("sardonyx.cardText", mode);
      site();
      const view = renderApp("/posts/5?tab=notes");
      const panel = await screen.findByRole("tabpanel");
      expect(panel.querySelector("iframe")).toBeNull();
      expect(screen.queryByRole("button", { name: /Load images/ })).toBeNull();
      expect(panel.querySelector("[data-text]")?.textContent).toBe(
        mode === "source" ? NOTES : "Made with",
      );
      view.unmount();
    }
  });
});
