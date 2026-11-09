import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import type { components } from "@/api/schema";
import { infoQuery } from "@/app/info";
import { usePrivileges } from "@/app/privileges";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type AppToken = components["schemas"]["AppToken"];

/** What a right is called here, and what it lets an app do, briefly. */
const RIGHT_LABELS: Record<string, { label: string; about: string }> = {
  read: { label: "Read", about: "See posts, cards, tags and pools" },
  write: { label: "Write", about: "Create posts and edit their tags and details" },
  upload: { label: "Upload", about: "Upload files" },
};

const DATE = new Intl.DateTimeFormat("en", { dateStyle: "medium" });

function formatDate(iso: string | null | undefined): string {
  if (!iso) {
    return "never";
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : DATE.format(date);
}

function rightLabel(right: string): string {
  return RIGHT_LABELS[right]?.label ?? right;
}

export function appTokensQuery(user: string) {
  return {
    queryKey: ["app-tokens", user],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      unwrap(
        api.GET("/app-tokens/{user_name}", {
          params: { path: { user_name: user } },
          signal,
        }),
      ),
  };
}

/** The end of the chosen day, here, as the site takes a time. */
function endOfDay(date: string): string {
  return new Date(`${date}T23:59:59`).toISOString();
}

function escapeCancels(onCancel: () => void) {
  return (event: KeyboardEvent) => {
    if (event.key === "Escape" && !event.defaultPrevented) {
      event.preventDefault();
      onCancel();
    }
  };
}

/**
 * The app tokens of the account: listed, made and revoked. A new token's
 * value is shown once, right after it was made, and is held by this view
 * only: not in the query cache, not in storage, not in the address. Leaving
 * the view (or pressing Done) forgets it; the site never gives it again.
 */
export function AppTokens({ user }: { user: string }) {
  const can = usePrivileges();
  if (!can?.("appTokens:list:self")) {
    return null;
  }
  return (
    <section aria-labelledby="app-tokens" className="flex flex-col gap-4">
      <h2 id="app-tokens" className="font-semibold">
        App tokens
      </h2>
      <p className="text-muted-foreground text-sm">
        A token lets another app use this site as you, but only for what its rights
        allow. It can never change your account or its tokens.
      </p>
      <TokenList user={user} canRevoke={can("appTokens:delete:self")} />
      {can("appTokens:create:self") ? <CreateToken user={user} /> : null}
    </section>
  );
}

function TokenList({ user, canRevoke }: { user: string; canRevoke: boolean }) {
  const tokens = useQuery(appTokensQuery(user));
  const [revoking, setRevoking] = useState<number | null>(null);

  if (tokens.isPending) {
    return <p className="text-muted-foreground text-sm">Loading the tokens…</p>;
  }
  if (tokens.isError) {
    return <ApiErrorMessage error={tokens.error} />;
  }
  const list = tokens.data.results ?? [];
  if (list.length === 0) {
    return <p className="text-muted-foreground text-sm">No app tokens yet.</p>;
  }
  return (
    <ul className="flex flex-col gap-2" aria-label="Your app tokens">
      {list.map((token) => (
        <li key={token.id} className="flex flex-col gap-2 rounded-xl border p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-medium">{token.name}</span>
            <span className="text-muted-foreground text-xs">
              {token.enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Rights</dt>
            <dd>{(token.rights ?? []).map(rightLabel).join(", ")}</dd>
            <dt className="text-muted-foreground">Created</dt>
            <dd>{formatDate(token.creationTime)}</dd>
            <dt className="text-muted-foreground">Last used</dt>
            <dd>{formatDate(token.lastUsageTime)}</dd>
            <dt className="text-muted-foreground">Expires</dt>
            <dd>{formatDate(token.expirationTime)}</dd>
          </dl>
          {canRevoke ? (
            revoking === token.id ? (
              <RevokeConfirmation
                user={user}
                token={token}
                onDone={() => setRevoking(null)}
              />
            ) : (
              <div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setRevoking(token.id ?? null)}
                >
                  Revoke
                </Button>
              </div>
            )
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function RevokeConfirmation({
  user,
  token,
  onDone,
}: {
  user: string;
  token: AppToken;
  onDone(): void;
}) {
  const id = useId();
  const client = useQueryClient();
  const cancel = useRef<HTMLButtonElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // opened, the focus goes to the safe choice
  useEffect(() => cancel.current?.focus(), []);

  const revoke = async () => {
    setBusy(true);
    setError(null);
    try {
      await unwrap(
        api.DELETE("/app-token/{user_name}/{token_id}", {
          params: { path: { user_name: user, token_id: String(token.id ?? "") } },
        }),
      );
      await client.invalidateQueries({ queryKey: ["app-tokens", user] });
      onDone();
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  };

  return (
    <section
      role="alertdialog"
      onKeyDown={escapeCancels(onDone)}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-text`}
      className="flex flex-col gap-3 rounded-xl border border-destructive bg-card p-4"
    >
      <h3 id={`${id}-title`} className="font-semibold">
        Revoke “{token.name}”?
      </h3>
      <p id={`${id}-text`} className="text-muted-foreground text-sm">
        The app using it is refused from now on. This cannot be undone.
      </p>
      {error ? <ApiErrorMessage error={error} /> : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="destructive" disabled={busy} onClick={revoke}>
          {busy ? "Revoking…" : `Revoke “${token.name}”`}
        </Button>
        <Button ref={cancel} variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </section>
  );
}

function CreateToken({ user }: { user: string }) {
  const info = useQuery(infoQuery);
  const client = useQueryClient();
  const rights = info.data?.appTokenRights ?? {};
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // the new token's value: in this component's state, nowhere else
  const [created, setCreated] = useState<{ name: string; value: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const valueField = useRef<HTMLInputElement>(null);
  const errorBox = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (created) {
      valueField.current?.focus();
    }
  }, [created]);
  useEffect(() => {
    if (error) {
      errorBox.current?.focus();
    }
  }, [error]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const name = String(form.get("name") ?? "").trim();
    const chosen = Object.keys(rights).filter((right) => form.get(`right-${right}`));
    const expires = String(form.get("expires") ?? "");
    setError(null);
    setBusy(true);
    try {
      const result = await unwrap(
        api.POST("/app-token/{user_name}", {
          params: { path: { user_name: user } },
          body: {
            name,
            rights: chosen,
            ...(expires ? { expirationTime: endOfDay(expires) } : {}),
          },
        }),
      );
      setCopied(false);
      setCreated({ name: result.name ?? name, value: result.token ?? "" });
      formElement.reset();
      // the list is asked for again: it has the token, without its value
      await client.invalidateQueries({ queryKey: ["app-tokens", user] });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!created) {
      return;
    }
    try {
      await navigator.clipboard.writeText(created.value);
      setCopied(true);
    } catch {
      // the browser did not allow it: the value is there to select
    }
  };

  if (created) {
    return (
      <div
        role="status"
        className="flex flex-col gap-3 rounded-xl border border-primary p-4"
      >
        <p className="text-sm">
          The token <strong>{created.name}</strong> is made. Copy it into the app now:
        </p>
        <div className="flex items-center gap-2">
          <Input
            ref={valueField}
            readOnly
            value={created.value}
            aria-label="The new token"
            onFocus={(event) => event.currentTarget.select()}
            className="min-w-0 flex-1 font-mono"
          />
          <Button
            variant="outline"
            size="icon"
            aria-label="Copy the token"
            onClick={copy}
          >
            {copied ? <Check /> : <Copy />}
          </Button>
        </div>
        <p className="text-muted-foreground text-sm">
          It won't be shown again. If it is lost, revoke it and make a new one.
        </p>
        <div>
          <Button variant="outline" onClick={() => setCreated(null)}>
            Done
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 rounded-xl border p-4">
      <h3 className="font-semibold">Make an app token</h3>
      <div className="flex flex-col gap-2">
        <Label htmlFor="app-token-name">Name</Label>
        <Input
          id="app-token-name"
          name="name"
          required
          maxLength={128}
          autoComplete="off"
          placeholder="What app it is for"
        />
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 font-medium text-sm">Rights</legend>
        {Object.entries(rights).map(([right, privileges]) => (
          <div key={right} className="flex items-start gap-2">
            <Checkbox
              id={`app-token-right-${right}`}
              name={`right-${right}`}
              className="mt-0.5"
            />
            <div className="flex flex-col">
              <Label htmlFor={`app-token-right-${right}`}>{rightLabel(right)}</Label>
              <span className="text-muted-foreground text-xs">
                {RIGHT_LABELS[right]?.about ?? ""}
                {RIGHT_LABELS[right] ? " — " : ""}
                {privileges.join(", ")}
              </span>
            </div>
          </div>
        ))}
      </fieldset>
      <div className="flex flex-col gap-2">
        <Label htmlFor="app-token-expires">Expires (optional)</Label>
        <Input id="app-token-expires" name="expires" type="date" />
      </div>
      {error ? (
        <div ref={errorBox} tabIndex={-1}>
          <ApiErrorMessage error={error} />
        </div>
      ) : null}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Making…" : "Make the token"}
        </Button>
      </div>
    </form>
  );
}
