import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { Check, Copy } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { api } from "@/api/client";
import { ApiError, unwrap } from "@/api/errors";
import { infoQuery } from "@/app/info";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const MAIL_NOT_CONFIGURED = "MailNotConfiguredError";

/** Why a site cannot reset a password by mail: said instead of the form. */
function NoMail() {
  return (
    <p className="text-muted-foreground text-sm">
      This site cannot send mail, so a password cannot be reset here. Ask the site's
      administrator to set a new one.
    </p>
  );
}

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-sm p-6">
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">{children}</CardContent>
      </Card>
    </main>
  );
}

/**
 * `/password-reset`: the name or email of an account, for the site to mail
 * it a link. The answer is the same whether the account exists, has an
 * email or not: the page does not tell who has an account here. Only a site
 * that cannot send mail says so.
 */
export function StartReset() {
  const info = useQuery(infoQuery);
  const [state, setState] = useState<"form" | "busy" | "sent">("form");
  const [error, setError] = useState<unknown>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const who = String(new FormData(event.currentTarget).get("who") ?? "").trim();
    if (!who) {
      return;
    }
    setState("busy");
    setError(null);
    try {
      await unwrap(
        api.GET("/password-reset/{user_name}", {
          params: { path: { user_name: who } },
        }),
      );
      setState("sent");
    } catch (failure) {
      // that the site cannot mail is the site's to say; an unknown account,
      // one without an email, any other answer: the same as a mail sent
      if (failure instanceof ApiError && failure.name === MAIL_NOT_CONFIGURED) {
        setError(failure);
        setState("form");
      } else if (failure instanceof ApiError && failure.status === 0) {
        // no answer at all: nothing was asked of the site
        setError(failure);
        setState("form");
      } else {
        setState("sent");
      }
    }
  };

  if (info.data && info.data.config?.canSendMails !== true) {
    return (
      <Page title="Reset your password">
        <NoMail />
      </Page>
    );
  }
  return (
    <Page title="Reset your password">
      {state === "sent" ? (
        <p role="status">
          If that account has an email, a link to reset its password is on its way. It
          works once, for a short time.
        </p>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="who">User name or email</Label>
            <Input id="who" name="who" autoComplete="username" required />
          </div>
          {error instanceof ApiError && error.name === MAIL_NOT_CONFIGURED ? (
            <NoMail />
          ) : error ? (
            <ApiErrorMessage error={error} />
          ) : null}
          <Button type="submit" disabled={state === "busy"}>
            {state === "busy" ? "Sending…" : "Send me a link"}
          </Button>
        </form>
      )}
      <Link
        to="/login"
        className="text-link text-sm underline-offset-4 hover:underline"
      >
        Back to logging in
      </Link>
    </Page>
  );
}

// The account and token of the link the mail held, between reading them
// off the address and confirming: in memory only, never in the address,
// the history or storage.
let pending: { user: string; token: string } | null = null;

/**
 * `/password-reset/<user>:<token>`, the link of the mail. The token is
 * taken off the address at once (the history entry is replaced), and kept
 * in memory for the confirmation. A name may hold a ':'; a token does not:
 * the split is at the last one.
 */
export function ResetLink() {
  const { nameToken } = useParams({ from: "/password-reset/$nameToken" });
  const navigate = useNavigate();
  useEffect(() => {
    const at = nameToken.lastIndexOf(":");
    pending =
      at > 0 && at < nameToken.length - 1
        ? { user: nameToken.slice(0, at), token: nameToken.slice(at + 1) }
        : null;
    navigate({ to: "/password-reset/confirm", replace: true });
  }, [nameToken, navigate]);
  return null;
}

/**
 * `/password-reset/confirm`: the reset the link asked for, made on a click.
 * The new password is shown once, to copy and change.
 */
export function ConfirmReset() {
  // read once: what the link held, as this page found it
  const [link] = useState(() => pending);
  const [state, setState] = useState<"ask" | "busy" | "done">("ask");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);

  if (!link) {
    return (
      <Page title="Reset your password">
        <p className="text-muted-foreground text-sm">
          This link is not complete. Open the link of the mail again, or ask for a new
          one.
        </p>
        <Link
          to="/password-reset"
          className="text-link text-sm underline-offset-4 hover:underline"
        >
          Ask for a new link
        </Link>
      </Page>
    );
  }

  const confirm = async () => {
    setState("busy");
    setError(null);
    try {
      const result = await unwrap(
        api.POST("/password-reset/{user_name}", {
          params: { path: { user_name: link.user } },
          body: { token: link.token },
        }),
      );
      // the token is used up: nothing of it is kept
      pending = null;
      setPassword(result.password ?? "");
      setState("done");
    } catch (failure) {
      setError(failure);
      setState("ask");
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
    } catch {
      // the browser did not allow it: the password is there to select
    }
  };

  if (state === "done") {
    return (
      <Page title="Your new password">
        <p className="text-sm">
          The password of <strong>{link.user}</strong> is now:
        </p>
        <div className="flex items-center gap-2">
          <Input
            readOnly
            value={password}
            aria-label="New password"
            onFocus={(event) => event.currentTarget.select()}
            className="min-w-0 flex-1 font-mono"
          />
          <Button
            variant="outline"
            size="icon"
            aria-label="Copy the password"
            onClick={copy}
          >
            {copied ? <Check /> : <Copy />}
          </Button>
        </div>
        <p className="text-muted-foreground text-sm">
          It is shown this once. Log in with it and change it now.
        </p>
        <Button asChild>
          <Link to="/login" search={{ redirect: "/account" }}>
            Log in and change it now
          </Link>
        </Button>
      </Page>
    );
  }
  return (
    <Page title="Reset your password">
      <p className="text-sm">
        Make a new password for <strong>{link.user}</strong>? The old one stops working.
      </p>
      {error ? <ApiErrorMessage error={error} /> : null}
      <Button onClick={confirm} disabled={state === "busy"}>
        {state === "busy" ? "Resetting…" : "Reset the password"}
      </Button>
    </Page>
  );
}
