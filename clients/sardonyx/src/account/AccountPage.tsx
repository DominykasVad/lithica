import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { api, basicAuthorization } from "@/api/client";
import { ApiError, unwrap } from "@/api/errors";
import { infoQuery } from "@/app/info";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * The site's rule for passwords (`passwordRegex` of GET /info), when this
 * browser can read it; the site checks it in any case.
 */
export function passwordRule(regex: string | undefined): RegExp | null {
  if (!regex) {
    return null;
  }
  try {
    return new RegExp(regex);
  } catch {
    // a rule written for the server only: the server says
    return null;
  }
}

/**
 * `/account`: changing one's password, and nothing else for now. The
 * current password is checked first (a request with it, which changes
 * nothing); the new one goes with the account's version, so that a change
 * made meanwhile elsewhere is not overwritten.
 */
export function AccountPage() {
  const auth = useAuth();
  const info = useQuery(infoQuery);
  const [state, setState] = useState<"form" | "busy" | "done">("form");
  const [error, setError] = useState<unknown>(null);

  if (!auth.user) {
    return (
      <main className="mx-auto max-w-sm p-6">
        <p className="text-muted-foreground">
          <Link
            to="/login"
            search={{ redirect: "/account" }}
            className="text-link underline-offset-4 hover:underline"
          >
            Log in
          </Link>{" "}
          to change your password.
        </p>
      </main>
    );
  }
  const user = auth.user;
  const rule = passwordRule(info.data?.config?.passwordRegex);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const current = String(form.get("current") ?? "");
    const next = String(form.get("new") ?? "");
    setError(null);
    if (rule && !rule.test(next)) {
      setError(
        new ApiError(
          "PasswordRule",
          "Not a password this site takes",
          `The new password must match ${info.data?.config?.passwordRegex}.`,
          400,
        ),
      );
      return;
    }
    setState("busy");
    try {
      // the current password, checked: the account read with it
      const account = await unwrap(
        api.GET("/user/{user_name}", {
          params: { path: { user_name: user } },
          headers: { Authorization: basicAuthorization(user, current) },
        }),
      );
      await unwrap(
        api.PUT("/user/{user_name}", {
          params: { path: { user_name: user } },
          body: { version: account.version ?? 0, password: next },
        }),
      );
      setState("done");
      formElement.reset();
    } catch (failure) {
      setError(
        failure instanceof ApiError &&
          failure.name === "AuthError" &&
          failure.status === 403
          ? new ApiError(
              failure.name,
              "The current password is wrong",
              "Type the password you log in with now.",
              403,
            )
          : failure,
      );
      setState("form");
    } finally {
      // the passwords are not left in the page, whatever happened
      for (const name of ["current", "new"]) {
        const field = formElement.elements.namedItem(name);
        if (field instanceof HTMLInputElement) {
          field.value = "";
        }
      }
    }
  };

  return (
    <main className="mx-auto max-w-sm p-6">
      <Card>
        <CardHeader>
          <CardTitle>Your account</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <h2 className="font-semibold">Change your password</h2>
            <div className="flex flex-col gap-2">
              <Label htmlFor="current">Current password</Label>
              <Input
                id="current"
                name="current"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="new">New password</Label>
              <Input
                id="new"
                name="new"
                type="password"
                autoComplete="new-password"
                required
              />
            </div>
            {error ? <ApiErrorMessage error={error} /> : null}
            {state === "done" ? <p role="status">Your password is changed.</p> : null}
            <Button type="submit" disabled={state === "busy"}>
              {state === "busy" ? "Changing…" : "Change the password"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
