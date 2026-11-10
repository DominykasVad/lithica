import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/api/client";
import { ApiError, unwrap } from "@/api/errors";
import type { components, operations } from "@/api/schema";
import { usePrivileges } from "@/app/privileges";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";

type Setting = components["schemas"]["SiteSetting"];
type Settings = components["schemas"]["SiteSettings"];
type Values = NonNullable<
  operations["update_site_settings"]["requestBody"]
>["content"]["application/json"]["values"];

const settingsQuery = {
  queryKey: ["site-settings"],
  queryFn: () => unwrap(api.GET("/site-settings")),
};

const labels: Record<string, [string, string]> = {
  visibility: ["Visibility", "Who can browse this site."],
  nsfw_tag: ["NSFW tag", "This tag and tags implying it mark NSFW posts."],
  nsfw_hide_names: [
    "Hide NSFW names",
    "Hide names and creators alongside NSFW pictures.",
  ],
  share_links_nsfw: ["Allow NSFW share links", "Allow bearer links to NSFW posts."],
  "features.pools": ["Pools", "Enable collections of posts."],
  "features.favorites": ["Favorites", "Enable favoriting posts."],
  "features.scores": ["Scores", "Enable up and down votes on posts and comments."],
  "features.notes": ["Notes", "Enable notes on pictures."],
  "features.comments": ["Comments", "Enable comments on posts."],
  name: ["Site name", "The name this server reports to clients."],
  contact_email: ["Contact email", "Public contact address; may be empty."],
  default_rank: ["Default account rank", "Rank given to new accounts."],
  password_reset_mail_interval: [
    "Password reset mail interval",
    "Minimum seconds between reset emails.",
  ],
};
const groups = [
  ["Access", ["visibility", "nsfw_tag", "nsfw_hide_names", "share_links_nsfw"]],
  ["Features", Object.keys(labels).filter((name) => name.startsWith("features."))],
  ["Site", ["name", "contact_email", "default_rank"]],
  ["Accounts", ["password_reset_mail_interval"]],
] as const;

function display(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : (JSON.stringify(value) ?? "");
}

function Editor({ answer, editable }: { answer: Settings; editable: boolean }) {
  const client = useQueryClient();
  const [changes, setChanges] = useState<Values>({});
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT("/site-settings", {
          body: { version: answer.version ?? 1, values: changes },
        }),
      ),
    onSuccess: async (next) => {
      setChanges({});
      client.setQueryData(settingsQuery.queryKey, next);
      await client.invalidateQueries();
    },
  });
  const change = (setting: Setting, value: Setting["value"]) => {
    if (!setting.name) return;
    const name = setting.name;
    setChanges((old) => {
      const next = { ...old };
      if (value === setting.value || (value === null && !setting.stored))
        delete next[name];
      else next[name] = value;
      return next;
    });
  };
  const field = (setting: Setting) => {
    const name = setting.name ?? "";
    const value =
      name in changes
        ? changes[name] === null
          ? setting.startingValue
          : changes[name]
        : setting.value;
    const disabled = !editable || save.isPending;
    const label = labels[name]?.[0] ?? name;
    return (
      <div key={name} className="space-y-2 border-b py-4">
        <Label htmlFor={name}>{label}</Label>
        {labels[name]?.[1] && (
          <p className="text-sm text-muted-foreground">{labels[name][1]}</p>
        )}
        {setting.type === "boolean" ? (
          <Switch
            id={name}
            checked={value === true}
            disabled={disabled}
            onCheckedChange={(value) => change(setting, value)}
          />
        ) : setting.type === "choice" ? (
          <RadioGroup
            id={name}
            aria-label={label}
            value={String(value)}
            disabled={disabled}
            onValueChange={(value) => change(setting, value)}
          >
            {setting.choices?.map((choice) => (
              <div key={choice} className="flex items-center gap-2">
                <RadioGroupItem id={`${name}-${choice}`} value={choice} />
                <Label htmlFor={`${name}-${choice}`}>{choice}</Label>
              </div>
            ))}
          </RadioGroup>
        ) : (
          <Input
            id={name}
            type={setting.type === "integer" ? "number" : "text"}
            min={setting.min ?? undefined}
            value={display(value)}
            disabled={disabled}
            onChange={(event) =>
              change(
                setting,
                setting.type === "integer"
                  ? Number(event.target.value)
                  : event.target.value,
              )
            }
          />
        )}
        {name === "visibility" && value !== "open" && !answer.fileLinksSigned && (
          <p role="alert" className="text-sm text-destructive">
            Post files stay reachable by anyone with an address. Configure signed file
            links to protect them.
          </p>
        )}
        {setting.stored && (
          <div className="flex items-center gap-3 text-sm">
            <span>config.yaml: {display(setting.startingValue)}</span>
            {editable && (
              <Button
                variant="outline"
                size="sm"
                disabled={save.isPending}
                onClick={() => change(setting, null)}
              >
                Reset {label}
              </Button>
            )}
          </div>
        )}
      </div>
    );
  };
  const settings = answer.settings ?? [];
  const unknown = settings.filter(
    (item) =>
      item.runtime &&
      !groups.some(([, names]) =>
        (names as readonly string[]).includes(item.name ?? ""),
      ),
  );
  const conflict = save.error instanceof ApiError && save.error.status === 409;
  return (
    <>
      {!editable && <p>Read-only: you do not have permission to edit site settings.</p>}
      {groups.map(([group, names]) => (
        <section key={group} className="space-y-2">
          <h2 className="mt-6 text-lg font-semibold">{group}</h2>
          {settings
            .filter(
              (item) =>
                item.runtime && (names as readonly string[]).includes(item.name ?? ""),
            )
            .map(field)}
        </section>
      ))}
      {unknown.length > 0 && (
        <section>
          <h2 className="mt-6 text-lg font-semibold">Other settings</h2>
          {unknown.map(field)}
        </section>
      )}
      <section>
        <h2 className="mt-6 text-lg font-semibold">Restart settings</h2>
        <p className="text-sm text-muted-foreground">
          Set in config.yaml; needs a restart
        </p>
        <dl>
          {settings
            .filter((item) => !item.runtime)
            .map((item) => (
              <div key={item.name} className="py-2">
                <dt className="font-medium">{item.name}</dt>
                <dd className="break-words text-sm">{display(item.value)}</dd>
              </div>
            ))}
        </dl>
      </section>
      {save.error && <ApiErrorMessage error={save.error} />}
      {conflict && (
        <Button
          variant="outline"
          onClick={async () => {
            await client.refetchQueries({ queryKey: settingsQuery.queryKey });
            setChanges({});
            save.reset();
          }}
        >
          Reload
        </Button>
      )}
      {editable && (
        <Button
          className="mt-6"
          disabled={Object.keys(changes).length === 0 || save.isPending || conflict}
          onClick={() => save.mutate()}
        >
          Save settings
        </Button>
      )}
    </>
  );
}

export function SiteSettings() {
  const can = usePrivileges();
  const query = useQuery({
    ...settingsQuery,
    enabled: can?.("siteSettings:view") ?? false,
  });
  if (!can) return <main className="mx-auto max-w-3xl p-6">Loading…</main>;
  if (!can("siteSettings:view"))
    return (
      <main className="mx-auto max-w-3xl p-6">
        You do not have permission to view site settings.
      </main>
    );
  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="text-2xl font-semibold">Site settings</h1>
      {query.error ? (
        <ApiErrorMessage error={query.error} />
      ) : query.data ? (
        <Editor
          key={query.data.version}
          answer={query.data}
          editable={can("siteSettings:edit")}
        />
      ) : (
        <p>Loading…</p>
      )}
    </main>
  );
}
