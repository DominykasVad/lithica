import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";
import { cardSaysNsfw } from "./cardTags";
import { refusal } from "./files";
import { charxCard, FakeXhr, pngCard } from "./fixtures";
import { send } from "./send";
import { tagsFor } from "./UploadPage";

const TOKEN = "f5a2c0de-0000-4000-8000-000000000001";
const ACCEPTED = [
  { mime: ["image/jpeg"], extensions: ["jpg", "jpeg", "jpe"] },
  { mime: ["image/png"], extensions: ["png"] },
  { mime: ["application/x-charx"], extensions: ["charx"] },
];
const SITE_INFO = {
  ...INFO,
  maxUploadSize: 1000,
  acceptedTypes: ACCEPTED,
  config: {
    ...INFO.config,
    privileges: { "uploads:create": "regular", "posts:create:identified": "regular" },
  },
};

const file = (name: string, bytes: Uint8Array | string = "x", type = "") =>
  new File([bytes as BlobPart], name, { type });

beforeEach(() => {
  FakeXhr.all = [];
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A site where `rank` is logged in as ada; POST /posts as `created` says. */
function site({
  rank = "regular",
  loggedIn = true,
  modules = ["cards"],
  info = {},
  created = (sent: Sent) => ({
    body: {
      id:
        40 +
        Number(String((sent.body as { contentToken: string }).contentToken).slice(-1)),
      type: "image",
      thumbnailUrl: "data/x.jpg",
      card: null,
    },
  }),
}: {
  rank?: string;
  loggedIn?: boolean;
  modules?: string[];
  /** more of GET /info, or other values */
  info?: Record<string, unknown>;
  created?: (sent: Sent) => { status?: number; body: unknown };
} = {}) {
  if (loggedIn) {
    sessionStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: TOKEN }),
    );
  }
  return fakeSite({
    "GET /info": { body: { ...SITE_INFO, modules, ...info } },
    "GET /user/ada": { body: { name: "ada", rank } },
    "GET /posts": { body: { total: 0, results: [] } },
    "POST /posts": created,
  } as never);
}

async function choose(...files: File[]) {
  const picker = await screen.findByTestId("file-picker");
  fireEvent.change(picker, { target: { files } });
}

const row = (name: string) => screen.getByRole("listitem", { name });
const postsSent = (sent: Sent[]) =>
  sent.filter((one) => one.method === "POST" && one.path.startsWith("/posts"));

describe("who may upload", () => {
  it("shows the link and the page to a user who may", async () => {
    site();
    renderApp("/upload");
    const banner = await screen.findByRole("banner");
    expect(await within(banner).findByRole("link", { name: "Upload" })).toHaveAttribute(
      "href",
      "/upload",
    );
    expect(
      await screen.findByRole("button", { name: "Choose files" }),
    ).toBeInTheDocument();
  });

  it("has no link for a user who may not, and the page says why", async () => {
    site({ rank: "restricted" });
    renderApp("/upload");
    expect(
      await screen.findByText(
        /cannot upload on this site: that takes the rank regular or higher/,
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("banner")).queryByRole("link", { name: "Upload" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Choose files" })).toBeNull();
  });

  it("asks a visitor to log in", async () => {
    site({ loggedIn: false });
    renderApp("/upload");
    expect(await screen.findByText(/Uploading needs an account/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("main")).getByRole("link", { name: "Log in" }),
    ).toHaveAttribute("href", "/login?redirect=%2Fupload");
  });
});

describe("files the site would refuse", () => {
  it("are marked at once with the reason, and not sent", async () => {
    site();
    renderApp("/upload");
    const user = userEvent.setup();
    await choose(
      file("big.png", "x".repeat(1001)),
      file("notes.txt", "hello", "text/plain"),
      file("readme"),
      file("photo.jpeg"),
    );
    expect(row("big.png")).toHaveTextContent(
      "Not sent: It is larger than this site takes (1000 bytes).",
    );
    expect(row("notes.txt")).toHaveTextContent(
      "Not sent: This site does not take .txt files.",
    );
    // nothing to go by: the site decides
    expect(row("readme")).toHaveTextContent("Ready");
    expect(row("photo.jpeg")).toHaveTextContent("Ready");
    await user.click(screen.getByRole("button", { name: "Upload 2 files" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(2));
    expect(FakeXhr.all.map((one) => one.file.name)).toEqual(["readme", "photo.jpeg"]);
  });

  it("are refused by size and well-known extension only; a listed type or MIME passes", () => {
    expect(refusal(file("a.charx"), 1000, ACCEPTED)).toBeNull();
    expect(refusal(file("a.charx"), 1000, ACCEPTED.slice(0, 2))).toBe(
      "This site does not take .charx files.",
    );
    expect(refusal(file("a.weird"), 1000, ACCEPTED)).toBeNull();
    expect(refusal(file("photo.unusual", "x", "image/png"), 1000, ACCEPTED)).toBeNull();
    expect(refusal(file("a.zip"), null, ACCEPTED)).toBe(
      "This site does not take .zip files.",
    );
  });
});

// on a site whose NSFW tag is the default one
const says = (one: File) => cardSaysNsfw(one, "nsfw");

describe("the NSFW box", () => {
  it("reads a card's own tags from a PNG or a CHARX, and nothing else", async () => {
    expect(await says(file("a.png", pngCard(["Fantasy", " NSFW "])))).toBe(true);
    expect(await says(file("a.png", pngCard(["nsfw"], "ccv3")))).toBe(true);
    expect(await says(file("a.png", pngCard(["fantasy"])))).toBe(false);
    expect(await says(file("a.charx", await charxCard(["NSFW"])))).toBe(true);
    expect(
      await says(file("a.charx", await charxCard(["nsfw"], { deflated: false }))),
    ).toBe(true);
    expect(await says(file("a.charx", await charxCard(["sfw"])))).toBe(false);
    // not cards, broken cards, cards past the limits: simply no
    expect(await says(file("a.jpg", "not a picture"))).toBe(false);
    expect(await says(file("a.png", pngCard("not a list")))).toBe(false);
    expect(await says(file("a.charx", "PK not a zip"))).toBe(false);
    expect(
      await says(
        file("a.charx", await charxCard(["nsfw"], { declaredSize: 100_000_000 })),
      ),
    ).toBe(false);
  });

  it("walks no more than 10,000 chunks of a PNG, nor past its end", async () => {
    const withPadding = (padding: number) =>
      says(file("a.png", pngCard(["nsfw"], "chara", { padding })));
    // IHDR, the padding and the card's chunk: within the bound, it is read
    expect(await withPadding(9_997)).toBe(true);
    // beyond it, the walk stops and the box starts unchecked
    expect(await withPadding(10_000)).toBe(false);
    expect(
      await says(file("a.png", pngCard(["nsfw"], "chara", { overlong: true }))),
    ).toBe(false);
  }, 20_000);

  it("is checked and held for a card that says NSFW, and sets the tag it is sent with", async () => {
    const sent = site();
    renderApp("/upload");
    const user = userEvent.setup();
    await user.type(await screen.findByRole("combobox", { name: /^Tags/ }), "sea NSFW");
    await choose(
      file("lewd.png", pngCard(["nsfw"])),
      file("lewd.charx", await charxCard(["NSFW"])),
      file("tame.png", pngCard(["sea"])),
      file("plain.jpg", "a picture"),
    );
    const box = (name: string) =>
      within(row(name)).getByRole("checkbox", { name: "NSFW" });
    const note = "This card is tagged NSFW by its creator; the site keeps that tag.";
    for (const name of ["lewd.png", "lewd.charx"]) {
      await waitFor(() => expect(box(name)).toBeChecked());
      // the site tags it so whatever is sent: the box says so and cannot be unticked
      expect(box(name)).toBeDisabled();
      expect(box(name)).toHaveAccessibleDescription(note);
      await user.click(box(name));
      expect(box(name)).toBeChecked();
    }
    for (const name of ["tame.png", "plain.jpg"]) {
      expect(box(name)).not.toBeChecked();
      expect(box(name)).toBeEnabled();
      expect(within(row(name)).queryByText(note)).toBeNull();
    }
    // checked by hand, it adds the tag; unchecked, it takes the batch's out
    await user.click(box("plain.jpg"));
    await user.click(screen.getByRole("button", { name: "Upload 4 files" }));
    for (let i = 0; i < 4; i++) {
      await waitFor(() => expect(FakeXhr.all.length).toBeGreaterThan(i));
      await act(async () => FakeXhr.all[i]?.respond(200, { token: `token-${i}` }));
    }
    await waitFor(() => expect(postsSent(sent)).toHaveLength(4));
    const tags = Object.fromEntries(
      postsSent(sent).map((one) => {
        const body = one.body as {
          contentToken: string;
          tags: string[];
          safety: string;
        };
        return [body.contentToken, body.tags];
      }),
    );
    expect(tags).toEqual({
      "token-0": ["sea", "nsfw"],
      "token-1": ["sea", "nsfw"],
      "token-2": ["sea"],
      "token-3": ["sea", "nsfw"],
    });
  });

  it("holds the box for a card that says NSFW even when it was unticked first", async () => {
    site();
    renderApp("/upload");
    const user = userEvent.setup();
    await screen.findByRole("combobox", { name: /^Tags/ });
    let answer: (nsfw: boolean) => void = () => {};
    const reading = new Promise<boolean>((resolve) => {
      answer = resolve;
    });
    const spy = vi.spyOn(await import("./cardTags"), "cardSaysNsfw");
    spy.mockReturnValue(reading);
    await choose(file("slow.png", pngCard(["nsfw"])));
    const box = within(row("slow.png")).getByRole("checkbox", { name: "NSFW" });
    await user.click(box);
    await user.click(box);
    expect(box).not.toBeChecked();
    await act(async () => answer(true));
    expect(box).toBeChecked();
    expect(box).toBeDisabled();
    spy.mockRestore();
  });

  it("is the viewer's alone on a site without cards, which asks no card field", async () => {
    const sent = site({ modules: [] });
    renderApp("/upload");
    const user = userEvent.setup();
    await screen.findByRole("combobox", { name: /^Tags/ });
    await choose(file("lewd.png", pngCard(["nsfw"])));
    const box = within(row("lewd.png")).getByRole("checkbox", { name: "NSFW" });
    // the card is not read: nothing checks or holds the box
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(box).not.toBeChecked();
    expect(box).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(1));
    await act(async () => FakeXhr.all[0]?.respond(200, { token: "token-1" }));
    await waitFor(() => expect(postsSent(sent)).toHaveLength(1));
    const [post] = postsSent(sent);
    expect(post?.path).toContain("fields=id%2Ctype%2CthumbnailUrl");
    expect(post?.path).not.toContain("card");
    expect(post?.body).toMatchObject({ tags: [] });
  });

  it("uses the site's NSFW tag, as GET /info names it", async () => {
    const sent = site({ info: { nsfwTag: "explicit" } });
    renderApp("/upload");
    const user = userEvent.setup();
    await user.type(await screen.findByRole("combobox", { name: /^Tags/ }), "sea");
    await choose(
      file("lewd.png", pngCard(["Explicit"])),
      file("other.png", pngCard(["nsfw"])),
    );
    const box = (name: string) =>
      within(row(name)).getByRole("checkbox", { name: "NSFW" });
    // the card that carries the site's tag; "nsfw" is just a tag on this site
    await waitFor(() => expect(box("lewd.png")).toBeChecked());
    expect(box("lewd.png")).toBeDisabled();
    expect(box("other.png")).not.toBeChecked();
    expect(screen.getByText("Checked NSFW adds the tag explicit.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Upload 2 files" }));
    for (let i = 0; i < 2; i++) {
      await waitFor(() => expect(FakeXhr.all.length).toBeGreaterThan(i));
      await act(async () => FakeXhr.all[i]?.respond(200, { token: `token-${i}` }));
    }
    await waitFor(() => expect(postsSent(sent)).toHaveLength(2));
    const tags = Object.fromEntries(
      postsSent(sent).map((one) => {
        const body = one.body as { contentToken: string; tags: string[] };
        return [body.contentToken, body.tags];
      }),
    );
    expect(tags).toEqual({ "token-0": ["sea", "explicit"], "token-1": ["sea"] });
  });

  it("reads the site's NSFW tag in a card, whatever its case", async () => {
    expect(await cardSaysNsfw(file("a.png", pngCard([" EXPLICIT "])), "explicit")).toBe(
      true,
    );
    expect(await cardSaysNsfw(file("a.png", pngCard(["nsfw"])), "explicit")).toBe(
      false,
    );
    expect(tagsFor("a Explicit nsfw", false, "explicit")).toEqual(["a", "nsfw"]);
    expect(tagsFor("a", true, "explicit")).toEqual(["a", "explicit"]);
  });

  it("keeps what the viewer chose over what the card says", () => {
    expect(tagsFor("a b a nsfw NSFW", false, "nsfw")).toEqual(["a", "b"]);
    expect(tagsFor("", true, "nsfw")).toEqual(["nsfw"]);
  });
});

describe("sending", () => {
  it("sends the file, shows how far, then makes the post with the batch's safety", async () => {
    const sent = site();
    renderApp("/upload");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("radio", { name: "Sketchy" }));
    await choose(file("one.png", pngCard(["sea"])));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(1));
    const request = FakeXhr.all[0] as FakeXhr;
    expect(request.url).toMatch(/\/api\/uploads$/);
    expect(request.headers.Authorization).toMatch(/^Token /);
    act(() => request.progress(50, 200));
    expect(within(row("one.png")).getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "25",
    );
    expect(row("one.png")).toHaveTextContent("Sending, 25%");
    await act(async () => request.respond(200, { token: "token-1" }));
    expect(
      await within(row("one.png")).findByRole("link", { name: "post 41" }),
    ).toHaveAttribute("href", "/posts/41");
    const body = postsSent(sent)[0]?.body as Record<string, unknown>;
    expect(body).toEqual({ safety: "sketchy", tags: [], contentToken: "token-1" });
    expect(postsSent(sent)[0]?.path).toContain(
      "fields=id%2Ctype%2CthumbnailUrl%2Ccard",
    );
  });

  it("sends two at a time", async () => {
    site();
    renderApp("/upload");
    const user = userEvent.setup();
    await choose(file("1.png"), file("2.png"), file("3.png"));
    await user.click(screen.getByRole("button", { name: "Upload 3 files" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(2));
    expect(row("3.png")).toHaveTextContent("Waiting");
    await act(async () => FakeXhr.all[0]?.respond(200, { token: "token-1" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(3));
    expect(FakeXhr.all[2]?.file.name).toBe("3.png");
  });

  it("cancels one file, or the rest, and a cancelled one can be tried again", async () => {
    site();
    renderApp("/upload");
    const user = userEvent.setup();
    await choose(file("1.png"), file("2.png"), file("3.png"), file("4.png"));
    await user.click(screen.getByRole("button", { name: "Upload 4 files" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(2));
    await user.click(within(row("1.png")).getByRole("button", { name: "Cancel" }));
    expect(FakeXhr.all[0]?.aborted).toBe(true);
    expect(await within(row("1.png")).findByText("Cancelled")).toBeInTheDocument();
    // the next one takes its place
    await waitFor(() => expect(FakeXhr.all).toHaveLength(3));
    await user.click(screen.getByRole("button", { name: "Cancel the rest" }));
    for (const name of ["2.png", "3.png", "4.png"]) {
      expect(await within(row(name)).findByText("Cancelled")).toBeInTheDocument();
    }
    expect(FakeXhr.all).toHaveLength(3);

    await user.click(within(row("4.png")).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(4));
    expect(FakeXhr.all[3]?.file.name).toBe("4.png");
  });

  it("lets a post being made finish, and shows how it ended", async () => {
    let answer: () => void = () => {};
    const sent = site({
      created: () =>
        new Promise((resolve) => {
          answer = () =>
            resolve({
              body: { id: 41, type: "image", thumbnailUrl: "data/x.jpg", card: null },
            });
        }) as never,
    });
    renderApp("/upload");
    const user = userEvent.setup();
    await choose(file("1.png"), file("2.png"), file("3.png"));
    await user.click(screen.getByRole("button", { name: "Upload 3 files" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(2));
    await act(async () => FakeXhr.all[0]?.respond(200, { token: "token-1" }));
    // its upload done, the post is being made: no cancelling it
    const creating = await within(row("1.png")).findByRole("button", {
      name: "Creating…",
    });
    expect(creating).toBeDisabled();
    expect(within(row("1.png")).queryByRole("button", { name: "Cancel" })).toBeNull();
    // the rest is cancelled, that one is left to finish
    await user.click(screen.getByRole("button", { name: "Cancel the rest" }));
    for (const name of ["2.png", "3.png"]) {
      expect(await within(row(name)).findByText("Cancelled")).toBeInTheDocument();
    }
    expect(FakeXhr.all[1]?.aborted).toBe(true);
    const post = postsSent(sent)[0];
    expect(post?.aborted).toBe(false);
    await act(async () => answer());
    expect(
      await within(row("1.png")).findByRole("link", { name: "post 41" }),
    ).toBeInTheDocument();
    expect(post?.aborted).toBe(false);
    // only the one post was asked for
    expect(postsSent(sent)).toHaveLength(1);
  });

  it("sends nothing for a file cancelled before it went", async () => {
    const cancelled = new AbortController();
    cancelled.abort();
    const sent = site();
    const outcome = await send(
      file("1.png"),
      { safety: "safe", tags: [] },
      { signal: cancelled.signal, cards: true, onProgress() {}, onCreating() {} },
    );
    expect(outcome).toEqual({ kind: "cancelled" });
    expect(FakeXhr.all).toHaveLength(0);
    expect(postsSent(sent)).toHaveLength(0);
  });

  it("asks before leaving while files are on their way", async () => {
    site();
    const view = renderApp("/upload");
    const user = userEvent.setup();
    await choose(file("1.png"));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(1));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await user.click(
      within(screen.getByRole("banner")).getByRole("link", { name: "Library" }),
    );
    expect(confirm).toHaveBeenCalledWith(
      "Files are still being uploaded. Leave and stop them?",
    );
    expect(view.router.state.location.pathname).toBe("/upload");
    confirm.mockReturnValue(true);
    await user.click(
      within(screen.getByRole("banner")).getByRole("link", { name: "Library" }),
    );
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/posts"));
    // and what was on its way is stopped
    expect(FakeXhr.all[0]?.aborted).toBe(true);
  });
});

describe("what became of each file", () => {
  it("a card post: its name and what the site found", async () => {
    site({
      created: () => ({
        body: {
          id: 7,
          type: "image",
          card: {
            name: "Mira",
            spec: "v2",
            format: "png",
            greetingCount: 3,
            lorebookEntryCount: 42,
          },
        },
      }),
    });
    renderApp("/upload");
    const user = userEvent.setup();
    await choose(file("mira.png", pngCard(["sea"])));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(1));
    await act(async () => FakeXhr.all[0]?.respond(200, { token: "token-1" }));
    expect(
      await within(row("mira.png")).findByRole("link", { name: "Mira" }),
    ).toHaveAttribute("href", "/posts/7");
    expect(row("mira.png")).toHaveTextContent(
      "Card V2, PNG, 3 greetings, lorebook of 42 entries",
    );
  });

  it("a duplicate: the post that has it", async () => {
    site({
      created: () => ({
        status: 400,
        body: {
          name: "PostAlreadyUploadedError",
          title: "Validation error",
          description: "Post already uploaded (12)",
          otherPostId: 12,
          otherPostUrl: "data/posts/12_x.png",
        },
      }),
    });
    renderApp("/upload");
    const user = userEvent.setup();
    await choose(file("again.png"));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(1));
    await act(async () => FakeXhr.all[0]?.respond(200, { token: "token-1" }));
    expect(
      await within(row("again.png")).findByRole("link", { name: "post 12" }),
    ).toHaveAttribute("href", "/posts/12");
    expect(row("again.png")).toHaveTextContent("Already on the site");
  });

  it("refused, when sent or when made a post: the site's title and description", async () => {
    site({
      created: () => ({
        status: 400,
        body: {
          name: "InvalidPostContentError",
          title: "Validation error",
          description: "The CHARX file holds more files than a card may.",
        },
      }),
    });
    renderApp("/upload");
    const user = userEvent.setup();
    await choose(file("bomb.charx"), file("huge.png"));
    await user.click(screen.getByRole("button", { name: "Upload 2 files" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(2));
    await act(async () => FakeXhr.all[0]?.respond(200, { token: "token-1" }));
    await act(async () =>
      FakeXhr.all[1]?.respond(
        413,
        {
          name: "RequestTooLargeError",
          title: "Payload Too Large",
          description: "The request is larger than the maximum of 1000 bytes.",
        },
        "Payload Too Large",
      ),
    );
    expect(
      await within(row("bomb.charx")).findByText("Refused: Validation error"),
    ).toBeInTheDocument();
    expect(row("bomb.charx")).toHaveTextContent(
      "The CHARX file holds more files than a card may.",
    );
    expect(
      await within(row("huge.png")).findByText("Refused: Payload Too Large"),
    ).toBeInTheDocument();
    // a refusal is the site's answer: no trying again
    expect(
      within(row("huge.png")).queryByRole("button", { name: "Try again" }),
    ).toBeNull();
  });

  it("failed to send: the error, and trying again sends it anew", async () => {
    site();
    renderApp("/upload");
    const user = userEvent.setup();
    await choose(file("flaky.png"));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(1));
    act(() => FakeXhr.all[0]?.fail());
    expect(await within(row("flaky.png")).findByText(/^Not sent:/)).toBeInTheDocument();
    await user.click(
      within(row("flaky.png")).getByRole("button", { name: "Try again" }),
    );
    await waitFor(() => expect(FakeXhr.all).toHaveLength(2));
    await act(async () => FakeXhr.all[1]?.respond(200, { token: "token-2" }));
    expect(
      await within(row("flaky.png")).findByRole("link", { name: "post 42" }),
    ).toBeInTheDocument();
  });

  it("Upload more starts a new list and keeps the batch's safety and tags", async () => {
    site();
    renderApp("/upload");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("radio", { name: "Unsafe" }));
    await user.type(screen.getByRole("combobox", { name: /^Tags/ }), "sea");
    await choose(file("1.png"));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    await waitFor(() => expect(FakeXhr.all).toHaveLength(1));
    await act(async () => FakeXhr.all[0]?.respond(200, { token: "token-1" }));
    await user.click(await screen.findByRole("button", { name: "Upload more" }));
    expect(screen.queryByRole("listitem", { name: "1.png" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Unsafe" })).toBeChecked();
    expect(screen.getByRole("combobox", { name: /^Tags/ })).toHaveValue("sea");
  });
});
