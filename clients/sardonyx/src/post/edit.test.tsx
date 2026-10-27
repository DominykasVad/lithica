import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CARD } from "@/card/fixtures";
import { MAX_FIELD_HEIGHT } from "@/search/CompletionInput";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";
import { changes, draftOf, listed, parseTags } from "./edit";
import { CATEGORIES, POST } from "./fixtures";

const TOKEN = "f5a2c0de-0000-4000-8000-000000000001";

/** The privileges of the tests' site: each field its own rank. */
const PRIVILEGES = {
  "posts:edit:tags": "regular",
  "posts:edit:safety": "power",
  "posts:edit:source": "regular",
  "posts:delete": "moderator",
  "tags:create": "regular",
  "tags:list": "regular",
};

const CONFLICT = {
  status: 409,
  body: {
    name: "IntegrityError",
    title: "Integrity violation",
    description: "Someone else modified this in the meantime. Please try again.",
  },
};

/**
 * A site where ada (of `rank`, or nobody when `rank` is null) looks at
 * post 5, version 3. The post is the site's state: an edit changes it, a
 * read gives it as it is; `answer` takes a request first when it wants to.
 */
function site({
  rank = "power" as string | null,
  privileges = PRIVILEGES as Record<string, string>,
  card = false,
  answer = (_sent: Sent): { status?: number; body: unknown } | null => null,
} = {}) {
  if (rank !== null) {
    sessionStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: TOKEN }),
    );
  }
  const state = {
    post: {
      ...POST,
      version: 3,
      card: card ? { name: "Mira Vell", spec: "v3", format: "charx" } : null,
    } as Record<string, unknown>,
  };
  const sent = fakeSite({
    "GET /info": { body: { ...INFO, config: { ...INFO.config, privileges } } },
    "GET /user/ada": { body: { name: "ada", rank } },
    "GET /post/5": (one: Sent) => answer(one) ?? { body: state.post },
    "PUT /post/5": (one: Sent) => {
      const refused = answer(one);
      if (refused) {
        return refused;
      }
      const body = one.body as Record<string, unknown>;
      // an edit of an older version is refused, as the site does
      if (body.version !== state.post.version) {
        return CONFLICT;
      }
      const { version: _version, tags, ...rest } = body;
      state.post = {
        ...state.post,
        ...rest,
        ...(tags
          ? {
              tags: (tags as string[]).map((name) => ({
                names: [name],
                category: "default",
                usages: 1,
              })),
            }
          : {}),
        version: (state.post.version as number) + 1,
      };
      return { body: state.post };
    },
    "DELETE /post/5": (one: Sent) =>
      answer(one) ??
      ((one.body as { version: number }).version === state.post.version
        ? { body: {} }
        : CONFLICT),
    "GET /post/5/around": { body: { prev: null, next: null } },
    "GET /tag-categories": { body: CATEGORIES },
    "GET /modules/cards/post/5": { body: CARD },
    "GET /posts": { body: { total: 0, results: [] } },
    // completion: the tags of the site that start with what was typed
    "GET /tags": (one: Sent) => {
      const query = new URLSearchParams(one.path.split("?")[1]).get("query") ?? "";
      const prefix = query.split("*")[0] ?? "";
      const names = ["lighthouse", "lightning", "coastal", "cove"].filter((name) =>
        name.startsWith(prefix),
      );
      return {
        body: {
          total: names.length,
          results: names.map((name) => ({
            names: [name],
            category: "default",
            usages: 1,
          })),
        },
      };
    },
  } as never);
  return { sent, state };
}

const edits = (sent: Sent[]) => sent.filter((one) => one.method === "PUT");

async function openEditor(name: RegExp = /^Edit /) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name }));
  return { user, form: await screen.findByRole("form", { name: "Edit post 5" }) };
}

describe("what is offered", () => {
  it("shows each field only to a rank that may change it", async () => {
    site({ rank: "regular" });
    renderApp("/posts/5");
    const { form } = await openEditor(/^Edit tags and source$/);
    expect(within(form).getByRole("textbox", { name: /^Tags/ })).toHaveValue(
      "mira_vell coastal a:b",
    );
    expect(within(form).getByRole("textbox", { name: /^Source/ })).toBeInTheDocument();
    expect(within(form).queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete post" })).toBeNull();
  });

  it("gives every field to a rank that has them all, and Delete to a moderator", async () => {
    site({ rank: "moderator" });
    renderApp("/posts/5");
    expect(
      await screen.findByRole("button", { name: "Edit tags, safety and source" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete post" })).toBeInTheDocument();
  });

  it("offers neither to a user who may do neither", async () => {
    site({
      rank: "restricted",
      privileges: {
        ...PRIVILEGES,
        "posts:edit:tags": "power",
        "posts:edit:source": "power",
      },
    });
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    await screen.findByText("Uploaded by");
    expect(screen.queryByRole("button", { name: /^Edit/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete post" })).toBeNull();
  });

  it("offers nothing to a visitor who is not logged in", async () => {
    site({ rank: null });
    renderApp("/posts/5");
    await screen.findByRole("heading", { name: "Post 5" });
    await screen.findByText("Uploaded by");
    expect(screen.queryByRole("button", { name: /^Edit/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete post" })).toBeNull();
  });

  it("says so when the rank cannot create tags", async () => {
    site({ rank: "power", privileges: { ...PRIVILEGES, "tags:create": "moderator" } });
    renderApp("/posts/5");
    const { form } = await openEditor();
    expect(form).toHaveTextContent("Your rank cannot create tags here");
  });
});

describe("editing", () => {
  it("sends only what changed, with the version edited", async () => {
    const { sent } = site();
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    const save = within(form).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await user.click(within(form).getByRole("radio", { name: "Unsafe" }));
    await user.click(save);
    await waitFor(() => expect(edits(sent)).toHaveLength(1));
    expect(edits(sent)[0]?.body).toEqual({ version: 3, safety: "unsafe" });
    expect(edits(sent)[0]?.path).toMatch(/fields=[^&]*version/);
  });

  it("sends the tags only when the list changed, not its order", async () => {
    const { sent } = site();
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    const tags = within(form).getByRole("textbox", { name: /^Tags/ });
    await user.clear(tags);
    await user.type(tags, "coastal a:b MIRA_VELL");
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
    // removing a tag is an ordinary edit of the tags, nsfw as much as any
    await user.clear(tags);
    await user.type(tags, "coastal");
    const source = within(form).getByRole("textbox", { name: /^Source/ });
    await user.clear(source);
    await user.type(source, "https://example.com/new");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(edits(sent)).toHaveLength(1));
    expect(edits(sent)[0]?.body).toEqual({
      version: 3,
      tags: ["coastal"],
      source: "https://example.com/new",
    });
  });

  it("shows the new state on the page and in the library's lists", async () => {
    site();
    const { queryClient } = renderApp("/posts/5");
    const listKey = ["posts", "page", "", 0, 50, "id,type,thumbnailUrl,safety"];
    queryClient.setQueryData(listKey, {
      total: 2,
      results: [
        { id: 4, type: "image", safety: "safe" },
        { id: 5, type: "image", safety: "sketchy" },
      ],
    });
    const { user, form } = await openEditor();
    await user.click(within(form).getByRole("radio", { name: "Unsafe" }));
    await user.click(within(form).getByRole("button", { name: "Save" }));
    // the editor closes on the post as the site now has it
    await waitFor(() => expect(screen.queryByRole("form")).toBeNull());
    const fact = screen.getByText("Safety", { selector: "dt" }).nextElementSibling;
    expect(fact).toHaveTextContent("unsafe");
    // the list keeps its own fields of the post, with the new values
    expect(queryClient.getQueryData(listKey)).toEqual({
      total: 2,
      results: [
        { id: 4, type: "image", safety: "safe" },
        { id: 5, type: "image", safety: "unsafe" },
      ],
    });
    // and is asked again when it is next shown
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
  });

  it("shows a card post's new tags beside its card", async () => {
    site({ card: true });
    renderApp("/posts/5");
    expect(
      await screen.findByRole("heading", { name: "Mira Vell" }),
    ).toBeInTheDocument();
    const { user, form } = await openEditor();
    const tags = within(form).getByRole("textbox", { name: /^Tags/ });
    await user.clear(tags);
    await user.type(tags, "coastal lighthouse");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    const list = await screen.findByRole("region", { name: "Tags" });
    await waitFor(() =>
      expect(
        within(list).getByRole("link", { name: /lighthouse/ }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("link", { name: /mira_vell/ })).toBeNull();
    // the card is still there, beside them
    expect(screen.getByRole("heading", { name: "Mira Vell" })).toBeInTheDocument();
  });

  it("says when it changed meanwhile, and reloads keeping the edits to redo", async () => {
    const { sent, state } = site();
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    // someone else saves first
    state.post = { ...state.post, version: 4, safety: "safe", source: "theirs" };
    await user.click(within(form).getByRole("radio", { name: "Unsafe" }));
    const source = within(form).getByRole("textbox", { name: /^Source/ });
    await user.clear(source);
    await user.type(source, "mine");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    const alert = await within(form).findByRole("alert");
    expect(alert).toHaveTextContent("Changed meanwhile by someone else");
    expect(alert).toHaveTextContent("Someone else modified this in the meantime.");

    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    // the fields show the post as it is now, nothing merged
    await waitFor(() =>
      expect(within(form).getByRole("radio", { name: "Safe" })).toBeChecked(),
    );
    expect(within(form).getByRole("textbox", { name: /^Source/ })).toHaveValue(
      "theirs",
    );
    // what the user had is beside them, to make again by hand
    const unsaved = within(form).getByRole("region", { name: "Your unsaved edits" });
    expect(unsaved).toHaveTextContent("SafetyUnsafe");
    expect(unsaved).toHaveTextContent("Sourcemine");
    expect(within(form).queryByRole("alert")).toBeNull();
    // the page shows the new post too
    const fact = screen
      .getAllByText("Safety", { selector: "dt" })
      .find((label) => !form.contains(label));
    expect(fact?.nextElementSibling).toHaveTextContent(/^safe$/);

    await user.click(within(form).getByRole("radio", { name: "Unsafe" }));
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(edits(sent)).toHaveLength(2));
    expect(edits(sent)[1]?.body).toEqual({ version: 4, safety: "unsafe" });
  });

  it("shows the site's own refusal", async () => {
    site({
      answer: (one) =>
        one.method === "PUT"
          ? {
              status: 403,
              body: {
                name: "AuthError",
                title: "Not allowed",
                description: "Insufficient privileges to edit safety.",
              },
            }
          : null,
    });
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    await user.click(within(form).getByRole("radio", { name: "Unsafe" }));
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Insufficient privileges to edit safety.",
    );
  });
});

describe("deleting", () => {
  it("asks first, naming the card, and goes back to where the library was", async () => {
    const { sent } = site({ rank: "moderator", card: true });
    const { router } = renderApp("/posts/5?q=sea&at=100");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete post" }));
    const confirm = screen.getByRole("alertdialog", {
      name: "Delete post 5 (Mira Vell)?",
    });
    expect(sent.some((one) => one.method === "DELETE")).toBe(false);
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Delete post" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Delete post 5 (Mira Vell)",
      }),
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/posts"));
    expect(router.state.location.searchStr).toBe("?q=sea&at=100");
    const deleted = sent.filter((one) => one.method === "DELETE");
    expect(deleted).toHaveLength(1);
    expect(deleted[0]?.body).toEqual({ version: 3 });
  });

  it("takes the post out of the library's lists", async () => {
    site({ rank: "moderator" });
    const { queryClient } = renderApp("/posts/5");
    const listKey = ["posts", "page", "sea", 0, 50, "id,type,thumbnailUrl"];
    queryClient.setQueryData(listKey, {
      total: 2,
      results: [{ id: 4 }, { id: 5 }],
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete post" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Delete post 5",
      }),
    );
    await waitFor(() =>
      expect(queryClient.getQueryData(listKey)).toEqual({
        total: 1,
        results: [{ id: 4 }],
      }),
    );
  });

  it("says when it changed meanwhile, and deletes the post as reloaded", async () => {
    const { sent, state } = site({ rank: "moderator" });
    const { router } = renderApp("/posts/5");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete post" }));
    // someone else edits it meanwhile
    state.post = { ...state.post, version: 4 };
    const confirm = screen.getByRole("alertdialog");
    await user.click(within(confirm).getByRole("button", { name: "Delete post 5" }));
    const alert = await within(confirm).findByRole("alert");
    expect(alert).toHaveTextContent("Changed meanwhile by someone else");
    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(within(confirm).queryByRole("alert")).toBeNull());
    // still asked: the post may be another now
    expect(router.state.location.pathname).toBe("/posts/5");
    await user.click(within(confirm).getByRole("button", { name: "Delete post 5" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/posts"));
    const deleted = sent.filter((one) => one.method === "DELETE");
    expect(deleted.map((one) => one.body)).toEqual([{ version: 3 }, { version: 4 }]);
  });
});

describe("the parts of an edit", () => {
  const post = { ...POST, version: 3 };

  it("reads the tags as names, each once", () => {
    expect(parseTags("  a b\tA  c\nb ")).toEqual(["a", "b", "c"]);
  });

  it("finds nothing changed in the post as it is", () => {
    expect(changes(post, draftOf(post), ["tags", "safety", "source"])).toEqual({});
  });

  it("leaves out what the user may not change", () => {
    const draft = { tags: "x", safety: "unsafe" as const, source: "y" };
    expect(changes(post, draft, ["safety"])).toEqual({ safety: "unsafe" });
    expect(changes(post, draft, [])).toEqual({});
  });

  it("names the fields for the button", () => {
    expect(listed(["tags"])).toBe("tags");
    expect(listed(["tags", "safety"])).toBe("tags and safety");
    expect(listed(["tags", "safety", "source"])).toBe("tags, safety and source");
  });

  it("sends an emptied source as empty", () => {
    expect(changes(post, { ...draftOf(post), source: "" }, ["source"])).toEqual({
      source: "",
    });
    // a field the post did not have is empty, not changed
    expect(
      changes({ ...post, source: null }, { ...draftOf(post), source: "" }, ["source"]),
    ).toEqual({});
  });
});

describe("focus", () => {
  it("goes to the tags when the editor opens, and back to Edit on Cancel", async () => {
    site();
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    expect(within(form).getByRole("textbox", { name: /^Tags/ })).toHaveFocus();
    await user.click(within(form).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("form")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Edit tags, safety and source" }),
    ).toHaveFocus();
  });

  it("goes back to Edit after a save", async () => {
    site();
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    await user.click(within(form).getByRole("radio", { name: "Unsafe" }));
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("form")).toBeNull());
    expect(
      screen.getByRole("button", { name: "Edit tags, safety and source" }),
    ).toHaveFocus();
  });

  it("closes the editor with Escape, but first the list of tags if it is open", async () => {
    const { sent } = site();
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    await user.type(within(form).getByRole("textbox", { name: /^Tags/ }), " light");
    await screen.findByRole("listbox", { name: "Tags" });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox", { name: "Tags" })).toBeNull();
    expect(screen.getByRole("form", { name: "Edit post 5" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("form")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Edit tags, safety and source" }),
    ).toHaveFocus();
    expect(edits(sent)).toHaveLength(0);
  });

  it("goes to the first field a rank may change", async () => {
    site({
      rank: "power",
      privileges: { ...PRIVILEGES, "posts:edit:tags": "moderator" },
    });
    renderApp("/posts/5");
    const { form } = await openEditor(/^Edit safety and source$/);
    expect(within(form).getByRole("radio", { name: "Sketchy" })).toHaveFocus();
  });

  it("goes to Cancel when a delete is to be confirmed, and back to Delete post", async () => {
    site({ rank: "moderator" });
    renderApp("/posts/5");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete post" }));
    const confirm = screen.getByRole("alertdialog");
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Delete post" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Delete post" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Delete post" })).toHaveFocus();
  });
});

describe("the tags field", () => {
  const many = Array.from({ length: 30 }, (_, i) => ({
    names: [`a_rather_long_tag_name_${String(i).padStart(2, "0")}`],
    category: "default",
    usages: 1,
  }));

  it("wraps a long list instead of scrolling sideways, and grows to a height", async () => {
    const { state } = site();
    state.post = { ...state.post, tags: many };
    renderApp("/posts/5");
    const { form } = await openEditor();
    const field = within(form).getByRole("textbox", { name: /^Tags/ });
    // a text area of one line of words: every tag in it, wrapped, never cut
    expect(field.tagName).toBe("TEXTAREA");
    expect(field).toHaveValue(many.map((tag) => tag.names[0]).join(" "));
    expect(field).not.toHaveAttribute("wrap", "off");
    expect(field).toHaveClass(
      "whitespace-pre-wrap",
      "wrap-anywhere",
      "overflow-x-hidden",
    );
    expect(field).toHaveClass("overflow-y-auto");
    expect(field.style.maxHeight).toBe(`${MAX_FIELD_HEIGHT}px`);
  });

  it("completes only the word at the cursor, in the middle of a wrapped list", async () => {
    const { state } = site();
    state.post = {
      ...state.post,
      tags: [...many.slice(0, 15), tag("lig"), ...many.slice(15)],
    };
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    const field = within(form).getByRole("textbox", {
      name: /^Tags/,
    }) as HTMLTextAreaElement;
    const before = field.value;
    const at = before.indexOf(" lig ") + 4;
    await user.type(field, "h", { initialSelectionStart: at, initialSelectionEnd: at });
    await screen.findByRole("option", { name: /lighthouse/ });
    await user.keyboard("{ArrowDown}{Enter}");
    expect(field.value).toBe(before.replace(" lig ", " lighthouse "));
    // Enter took the tag: no line break, and the form was not sent
    expect(field.value).not.toMatch(/\n/);
    expect(screen.getByRole("form", { name: "Edit post 5" })).toBeInTheDocument();
  });

  it("keeps the words on one line: Enter adds no break, a pasted one is a space", async () => {
    site();
    renderApp("/posts/5");
    const { user, form } = await openEditor();
    const field = within(form).getByRole("textbox", { name: /^Tags/ });
    await user.type(field, "{Enter}");
    expect(field).toHaveValue("mira_vell coastal a:b");
    await user.paste("\nsea\r\nfoam");
    // (a pasted CRLF reaches the field as one break: the browser makes it so)
    expect(field).toHaveValue("mira_vell coastal a:b sea foam");
    expect(
      changes({ ...POST, version: 3 }, { ...draftOf(POST), tags: "a b" }, ["tags"]),
    ).toEqual({
      tags: ["a", "b"],
    });
  });
});

function tag(name: string) {
  return { names: [name], category: "default", usages: 1 };
}
