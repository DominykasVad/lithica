import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import type { components, operations } from "@/api/schema";
import { infoQuery } from "@/app/info";
import { usePrivileges } from "@/app/privileges";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Post } from "./queries";

type CreateShareLink = NonNullable<
  operations["create_share_link"]["requestBody"]
>["content"]["application/json"];

type ShareLink = components["schemas"]["ShareLink"];
export const SHARE_LINK_PRIVILEGES = [
  "shareLinks:create",
  "shareLinks:list:self",
  "shareLinks:list:any",
  "shareLinks:delete:self",
  "shareLinks:delete:any",
] as const;
const DATE = new Intl.DateTimeFormat("en", { dateStyle: "medium" });
const date = (value: string) => DATE.format(new Date(value));

/** Shared by post and account views; both lists must reflect every change. */
export async function refreshShareLinks(client: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    client.invalidateQueries({ queryKey: ["share-links", "post"] }),
    client.invalidateQueries({ queryKey: ["share-links", "user"] }),
  ]);
}

export function ShareLinkRow({
  link,
  blocked = false,
  focusCopy = false,
  onRevoked,
}: {
  link: ShareLink;
  blocked?: boolean;
  focusCopy?: boolean;
  onRevoked?(): void;
}) {
  const { user } = useAuth();
  const can = usePrivileges();
  const client = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copying, setCopying] = useState(false);
  const copyButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const revokeButton = useRef<HTMLButtonElement>(null);
  const id = useId();
  const url = link.url
    ? /^[a-z][a-z\d+.-]*:/i.test(link.url)
      ? link.url
      : new URL(link.url, window.location.origin).href
    : "";
  const mayDelete =
    can?.("shareLinks:delete:any") ||
    (link.user?.name === user && can?.("shareLinks:delete:self"));
  useEffect(() => {
    if (focusCopy) copyButton.current?.focus();
  }, [focusCopy]);
  useEffect(() => {
    if (confirm) cancelButton.current?.focus();
  }, [confirm]);
  const revoke = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/share-link/{link_id}", {
          params: { path: { link_id: link.id ?? 0 } },
        }),
      ),
    onSuccess: async () => {
      onRevoked?.();
      await refreshShareLinks(client);
    },
  });
  const close = () => {
    setConfirm(false);
    revokeButton.current?.focus();
  };
  return (
    <li
      className={`flex min-w-0 flex-col gap-2 rounded-xl border p-3 text-sm ${link.expired ? "text-muted-foreground" : ""}`}
    >
      <p className="break-words font-medium">{link.note || "No note"}</p>
      {link.user?.name && link.user.name !== user ? <p>By {link.user.name}</p> : null}
      {link.creationTime ? <p>Created {date(link.creationTime)}</p> : null}
      <p>
        Expires:{" "}
        {link.expired ? "Expired" : link.expiresAt ? date(link.expiresAt) : "Never"}
      </p>
      {blocked ? <p>Not delivered while the post is NSFW</p> : null}
      <div className="flex gap-2">
        <Input
          readOnly
          aria-label="Share link URL"
          value={url}
          onFocus={(event) => event.currentTarget.select()}
          className="min-w-0 font-mono"
        />
        <Button
          ref={copyButton}
          variant="outline"
          size="icon"
          aria-label="Copy share link"
          disabled={copying || revoke.isPending}
          onClick={async () => {
            setCopying(true);
            try {
              await navigator.clipboard.writeText(url);
              setCopied(true);
            } catch {
              /* The URL remains selectable when clipboard access is refused. */
            } finally {
              setCopying(false);
            }
          }}
        >
          {copied ? <Check /> : <Copy />}
        </Button>
      </div>
      {mayDelete ? (
        <Button
          ref={revokeButton}
          variant="ghost"
          disabled={revoke.isPending}
          onClick={() => setConfirm(true)}
        >
          Revoke
        </Button>
      ) : null}
      {confirm ? (
        <section
          role="alertdialog"
          aria-labelledby={`${id}-title`}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !revoke.isPending) close();
          }}
          className="flex flex-col gap-2 rounded-xl border border-destructive p-3"
        >
          <h3 id={`${id}-title`}>Revoke this share link?</h3>
          <p>Anyone with this link will lose access to the file.</p>
          {revoke.isError ? <ApiErrorMessage error={revoke.error} /> : null}
          <Button
            variant="destructive"
            disabled={revoke.isPending}
            onClick={() => revoke.mutate()}
          >
            Confirm revoke
          </Button>
          <Button
            ref={cancelButton}
            variant="outline"
            disabled={revoke.isPending}
            onClick={close}
          >
            Cancel
          </Button>
        </section>
      ) : null}
    </li>
  );
}

export function ShareLinks({ post }: { post: Post }) {
  const { user } = useAuth();
  const can = usePrivileges();
  if (
    !user ||
    !(
      can?.("shareLinks:create") ||
      can?.("shareLinks:list:self") ||
      can?.("shareLinks:list:any")
    )
  )
    return null;
  return <PostShareLinks key={post.id} post={post} />;
}

function PostShareLinks({ post }: { post: Post }) {
  const can = usePrivileges();
  const info = useQuery(infoQuery);
  const client = useQueryClient();
  const id = post.id ?? 0;
  const formId = useId();
  const [created, setCreated] = useState<ShareLink | null>(null);
  const mayList = Boolean(
    can?.("shareLinks:list:self") || can?.("shareLinks:list:any"),
  );
  const list = useQuery({
    queryKey: ["share-links", "post", id],
    enabled: mayList,
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/post/{post_id}/share-links", {
          params: { path: { post_id: id } },
          signal,
        }),
      ),
  });
  const blocked = post.nsfw === true && info.data?.shareLinksNsfw === false;
  const create = useMutation({
    mutationFn: (body: CreateShareLink) =>
      unwrap(
        api.POST("/post/{post_id}/share-links", {
          params: { path: { post_id: id } },
          body,
        }),
      ),
    onSuccess: async (link) => {
      setCreated(link);
      await refreshShareLinks(client);
    },
  });
  const links = list.data?.results ?? [];
  const shown =
    created && !links.some((link) => link.id === created.id) && !mayList
      ? [...links, created]
      : links;
  const today = new Date();
  const minimum = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return (
    <section aria-label="Share links" className="flex min-w-0 flex-col gap-3">
      <h2 className="font-semibold">Share links</h2>
      {list.isError ? <ApiErrorMessage error={list.error} /> : null}
      {mayList && list.isPending ? (
        <p className="text-muted-foreground text-sm">Loading share links…</p>
      ) : null}
      {list.isSuccess && !shown.length ? (
        <p className="text-muted-foreground text-sm">No share links yet.</p>
      ) : null}
      <ul aria-label="Post share links" className="flex flex-col gap-3">
        {shown.map((link) => (
          <ShareLinkRow
            key={link.id}
            link={link}
            blocked={blocked}
            focusCopy={created?.id === link.id}
            onRevoked={() => {
              if (created?.id === link.id) setCreated(null);
            }}
          />
        ))}
      </ul>
      {blocked ? (
        <p className="text-muted-foreground text-sm">
          Share links for NSFW posts are off on this site.
        </p>
      ) : can?.("shareLinks:create") ? (
        <form
          className="flex flex-col gap-3 rounded-xl border p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (create.isPending) return;
            const form = event.currentTarget;
            const values = new FormData(form);
            const note = String(values.get("note") ?? "");
            const expires = String(values.get("expires") ?? "");
            create.mutate(
              {
                ...(note ? { note } : {}),
                ...(expires
                  ? { expiresAt: new Date(`${expires}T23:59:59`).toISOString() }
                  : {}),
              },
              { onSuccess: () => form.reset() },
            );
          }}
        >
          <Label htmlFor={`${formId}-note`}>Note (optional)</Label>
          <Input id={`${formId}-note`} name="note" maxLength={128} />
          <Label htmlFor={`${formId}-expires`}>Expires (optional)</Label>
          <Input id={`${formId}-expires`} name="expires" type="date" min={minimum} />
          {create.isError ? <ApiErrorMessage error={create.error} /> : null}
          <Button type="submit" disabled={create.isPending}>
            Create link
          </Button>
        </form>
      ) : null}
    </section>
  );
}
