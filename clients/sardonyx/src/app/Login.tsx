import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { infoQuery } from "./info";

/**
 * Logging in. The password goes to the site once, to make a login token,
 * and is not kept, in the page or anywhere else.
 */
export function Login({ redirect }: { redirect?: string }) {
  const auth = useAuth();
  const navigate = useNavigate();
  const info = useQuery(infoQuery);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // kept now: the event lets go of its target once the handler awaits
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const user = String(form.get("user") ?? "").trim();
    const password = String(form.get("password") ?? "");
    setBusy(true);
    setError(null);
    try {
      await auth.logIn(user, password, form.get("remember") === "on");
      // only a path of this app: a link must not send the user elsewhere
      navigate({
        to: redirect?.startsWith("/") && !redirect.startsWith("//") ? redirect : "/",
      });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
      // the password is not left in the page, whatever happened
      const passwordField = formElement.elements.namedItem("password");
      if (passwordField instanceof HTMLInputElement) {
        passwordField.value = "";
      }
    }
  };

  return (
    <main className="mx-auto max-w-sm p-6">
      <Card>
        <CardHeader>
          <CardTitle>Log in</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="user">User name</Label>
              <Input id="user" name="user" autoComplete="username" required />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox id="remember" name="remember" />
              <Label htmlFor="remember">Remember me on this browser</Label>
            </div>
            {error ? <ApiErrorMessage error={error} /> : null}
            <Button type="submit" disabled={busy}>
              {busy ? "Logging in…" : "Log in"}
            </Button>
            {info.data?.config?.canSendMails ? (
              <Link
                to="/password-reset"
                className="text-link text-sm underline-offset-4 hover:underline"
              >
                Forgot your password?
              </Link>
            ) : null}
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
