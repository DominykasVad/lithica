import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Pencil, RotateCcw, Trash2 } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { api } from "@/api/client";
import { asApiError, unwrap } from "@/api/errors";
import { usePrivileges } from "@/app/privileges";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { LibrarySearch } from "@/library/search";
import { CompletionInput } from "@/search/CompletionInput";
import {
  changes,
  DELETE_PRIVILEGE,
  type Draft,
  deletedPost,
  draftOf,
  type EditField,
  editableFields,
  listed,
  type Safety,
  savedPost,
} from "./edit";
import { type Post, postQuery } from "./queries";

const SAFETIES = ["safe", "sketchy", "unsafe"] as const;
const SAFETY_LABELS = { safe: "Safe", sketchy: "Sketchy", unsafe: "Unsafe" } as const;

/** Escape, unless something inside (the list of tags) took it first, cancels. */
function escapeCancels(onCancel: () => void) {
  return (event: KeyboardEvent) => {
    if (event.key === "Escape" && !event.defaultPrevented) {
      event.preventDefault();
      onCancel();
    }
  };
}

/** An edit or a delete refused because the post changed since it was read. */
const isConflict = (error: unknown) => asApiError(error).status === 409;

/**
 * The post was changed by someone else since it was read: what the site
 * said, and a way to read it again.
 */
function Conflict({
  error,
  onReload,
  reloading,
}: {
  error: unknown;
  onReload(): void;
  reloading: boolean;
}) {
  return (
    <Alert variant="destructive" role="alert">
      <AlertTitle>Changed meanwhile by someone else</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-2">
        <span>{asApiError(error).description}</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onReload}
          disabled={reloading}
        >
          <RotateCcw />
          Reload
        </Button>
      </AlertDescription>
    </Alert>
  );
}

/** The edit that could not be saved, to be made again by hand on the new post. */
function UnsavedEdits({
  base,
  draft,
  fields,
  onDismiss,
}: {
  base: Post;
  draft: Draft;
  fields: readonly EditField[];
  onDismiss(): void;
}) {
  const changed = changes(base, draft, fields);
  return (
    <section
      aria-label="Your unsaved edits"
      className="flex flex-col gap-2 rounded-xl border border-warn bg-card p-3 text-sm"
    >
      <h3 className="font-semibold">Your unsaved edits</h3>
      <p className="text-muted-foreground">
        The fields below show the post as it is now. What you had changed is here, to
        make again where it still applies:
      </p>
      <dl className="flex flex-col gap-1.5">
        {changed.tags ? (
          <div>
            <dt className="text-muted-foreground text-xs">Tags</dt>
            <dd className="break-words font-mono">
              {changed.tags.join(" ") || "none"}
            </dd>
          </div>
        ) : null}
        {changed.safety ? (
          <div>
            <dt className="text-muted-foreground text-xs">Safety</dt>
            <dd>{SAFETY_LABELS[changed.safety]}</dd>
          </div>
        ) : null}
        {changed.source !== undefined ? (
          <div>
            <dt className="text-muted-foreground text-xs">Source</dt>
            <dd className="whitespace-pre-wrap break-all">
              {changed.source || "none"}
            </dd>
          </div>
        ) : null}
      </dl>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={onDismiss}
      >
        Dismiss
      </Button>
    </section>
  );
}

function Editor({
  post,
  fields,
  postFields,
  canCreateTags,
  onDone,
}: {
  post: Post;
  fields: readonly EditField[];
  postFields: string;
  canCreateTags: boolean;
  onDone(): void;
}) {
  const id = useId();
  const client = useQueryClient();
  const postId = post.id ?? 0;
  // the post the edit is made on: its version goes with the request
  const [base, setBase] = useState(post);
  const [draft, setDraft] = useState(() => draftOf(post));
  // an edit the site refused as made on an older post, kept to be redone
  const [unsaved, setUnsaved] = useState<{ base: Post; draft: Draft } | null>(null);
  const changed = changes(base, draft, fields);
  const dirty = Object.keys(changed).length > 0;
  const form = useRef<HTMLFormElement>(null);

  // opened, the focus goes to the first field: in the order shown, the
  // tags, the chosen safety, the source
  useEffect(() => {
    form.current
      ?.querySelector<HTMLElement>("textarea, [role=radio][aria-checked=true]")
      ?.focus();
  }, []);

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT("/post/{post_id}", {
          params: { path: { post_id: String(postId) }, query: { fields: postFields } },
          body: { version: base.version ?? 0, ...changed },
        }),
      ),
    onSuccess: (saved) => {
      savedPost(client, saved);
      onDone();
    },
  });

  const reload = useMutation({
    mutationFn: () =>
      client.fetchQuery({ ...postQuery(postId, postFields), staleTime: 0 }),
    onSuccess: (fresh) => {
      // the post as it is now, in the fields; what the user had, beside them
      setUnsaved({ base, draft });
      setBase(fresh);
      setDraft(draftOf(fresh));
      save.reset();
    },
  });

  return (
    <form
      ref={form}
      aria-label={`Edit post ${postId}`}
      onKeyDown={escapeCancels(onDone)}
      className="flex flex-col gap-4 rounded-xl border bg-card p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (dirty && !save.isPending) {
          save.mutate();
        }
      }}
    >
      {unsaved ? (
        <UnsavedEdits
          base={unsaved.base}
          draft={unsaved.draft}
          fields={fields}
          onDismiss={() => setUnsaved(null)}
        />
      ) : null}
      {fields.includes("tags") ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${id}-tags`} className="font-semibold text-sm">
            Tags{" "}
            <span className="font-normal text-muted-foreground">
              (separated by spaces)
            </span>
          </label>
          <CompletionInput
            id={`${id}-tags`}
            mode="names"
            multiline
            value={draft.tags}
            onChange={(tags) => setDraft((now) => ({ ...now, tags }))}
          />
          {canCreateTags ? null : (
            <p className="text-muted-foreground text-xs">
              Your rank cannot create tags here: use tags the site has.
            </p>
          )}
        </div>
      ) : null}
      {fields.includes("safety") ? (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1.5 font-semibold text-sm">Safety</legend>
          <RadioGroup
            value={draft.safety}
            onValueChange={(value) =>
              setDraft((now) => ({ ...now, safety: value as Safety }))
            }
            className="flex flex-wrap gap-4"
          >
            {SAFETIES.map((one) => (
              <div key={one} className="flex items-center gap-2">
                <RadioGroupItem id={`${id}-${one}`} value={one} />
                <Label htmlFor={`${id}-${one}`} className="font-normal">
                  {SAFETY_LABELS[one]}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </fieldset>
      ) : null}
      {fields.includes("source") ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${id}-source`} className="font-semibold text-sm">
            Source{" "}
            <span className="font-normal text-muted-foreground">(one per line)</span>
          </label>
          <textarea
            id={`${id}-source`}
            value={draft.source}
            onChange={(event) =>
              setDraft((now) => ({ ...now, source: event.target.value }))
            }
            rows={3}
            className="w-full rounded-xl border border-control-border bg-card px-3 py-2 text-foreground text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
      ) : null}
      {save.isError ? (
        isConflict(save.error) ? (
          <Conflict
            error={save.error}
            onReload={() => reload.mutate()}
            reloading={reload.isPending}
          />
        ) : (
          <ApiErrorMessage error={save.error} />
        )
      ) : null}
      {reload.isError ? <ApiErrorMessage error={reload.error} /> : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        {dirty ? null : (
          <span className="text-muted-foreground text-sm">Nothing changed yet.</span>
        )}
      </div>
    </form>
  );
}

function DeleteConfirmation({
  post,
  name,
  postFields,
  from,
  onCancel,
}: {
  post: Post;
  name: string | null;
  postFields: string;
  from: LibrarySearch;
  onCancel(): void;
}) {
  const id = useId();
  const client = useQueryClient();
  const navigate = useNavigate();
  const postId = post.id ?? 0;
  const what = name ? `post ${postId} (${name})` : `post ${postId}`;
  const cancel = useRef<HTMLButtonElement>(null);

  // opened, the focus goes to the safe choice
  useEffect(() => cancel.current?.focus(), []);

  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/post/{post_id}", {
          params: { path: { post_id: String(postId) } },
          body: { version: post.version ?? 0 },
        }),
      ),
    onSuccess: async () => {
      // back to where the library was, then the post out of what is kept
      await navigate({ to: "/posts", search: from });
      deletedPost(client, postId);
    },
  });
  const reload = useMutation({
    mutationFn: () =>
      client.fetchQuery({ ...postQuery(postId, postFields), staleTime: 0 }),
    onSuccess: () => remove.reset(),
  });

  return (
    <section
      role="alertdialog"
      onKeyDown={escapeCancels(onCancel)}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-text`}
      className="flex flex-col gap-3 rounded-xl border border-destructive bg-card p-4"
    >
      <h3 id={`${id}-title`} className="font-semibold">
        Delete {what}?
      </h3>
      <p id={`${id}-text`} className="text-muted-foreground text-sm">
        The post and its file are deleted from the site. This cannot be undone.
      </p>
      {remove.isError ? (
        isConflict(remove.error) ? (
          <Conflict
            error={remove.error}
            onReload={() => reload.mutate()}
            reloading={reload.isPending}
          />
        ) : (
          <ApiErrorMessage error={remove.error} />
        )
      ) : null}
      {reload.isError ? <ApiErrorMessage error={reload.error} /> : null}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="destructive"
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          {remove.isPending ? "Deleting…" : `Delete ${what}`}
        </Button>
        <Button ref={cancel} variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </section>
  );
}

/**
 * Edit and Delete on a post page, as far as this user may: Edit shows the
 * fields their rank can change, Delete only with the privilege to delete.
 * Nothing is shown to a user who may do neither.
 */
export function PostActions({
  post,
  name,
  postFields,
  from,
}: {
  post: Post;
  /** the card's name, for the confirmation of a delete */
  name: string | null;
  postFields: string;
  from: LibrarySearch;
}) {
  const can = usePrivileges();
  const fields = editableFields(can);
  const canDelete = can?.(DELETE_PRIVILEGE) ?? false;
  const [open, setOpen] = useState<"edit" | "delete" | null>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  // closed, the focus goes back to the button that opened it
  const returnTo = useRef<"edit" | "delete" | null>(null);
  useEffect(() => {
    if (open === null && returnTo.current) {
      (returnTo.current === "edit" ? editButton : deleteButton).current?.focus();
      returnTo.current = null;
    }
  }, [open]);
  const close = (which: "edit" | "delete") => {
    returnTo.current = which;
    setOpen(null);
  };
  if (!fields.length && !canDelete) {
    return null;
  }
  return (
    <div className="flex flex-col gap-2">
      {open === "edit" ? (
        <Editor
          // a new post is a new edit
          key={post.id}
          post={post}
          fields={fields}
          postFields={postFields}
          canCreateTags={can?.("tags:create") ?? false}
          onDone={() => close("edit")}
        />
      ) : fields.length ? (
        <Button
          ref={editButton}
          variant="outline"
          className="h-11 rounded-xl"
          onClick={() => setOpen("edit")}
        >
          <Pencil />
          Edit {listed(fields)}
        </Button>
      ) : null}
      {open === "delete" ? (
        <DeleteConfirmation
          post={post}
          name={name}
          postFields={postFields}
          from={from}
          onCancel={() => close("delete")}
        />
      ) : canDelete && open === null ? (
        <Button
          ref={deleteButton}
          variant="ghost"
          className="h-11 rounded-xl text-destructive hover:text-destructive"
          onClick={() => setOpen("delete")}
        >
          <Trash2 />
          Delete post
        </Button>
      ) : null}
    </div>
  );
}
