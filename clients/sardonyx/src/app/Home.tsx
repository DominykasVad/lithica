import { useQuery } from "@tanstack/react-query";
import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import { infoQuery } from "./info";

type Info = components["schemas"]["Info"];

// Every field of an API resource is optional in its type: a request can ask
// for some fields only. What is not there is shown as not known.
function SiteFacts({ info }: { info: Info }) {
  const modules = info.modules ?? [];
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
      <dt className="text-muted-foreground">Site</dt>
      <dd>{info.config?.name ?? "?"}</dd>
      <dt className="text-muted-foreground">Posts</dt>
      <dd>{info.postCount ?? "?"}</dd>
      <dt className="text-muted-foreground">Modules</dt>
      <dd>{modules.length ? modules.join(", ") : "none"}</dd>
    </dl>
  );
}

/** The start page, for now: what the site says about itself. */
export function Home() {
  const info = useQuery(infoQuery);

  return (
    <main className="mx-auto flex max-w-xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">Sardonyx</h1>
      {info.isPending && <p>Asking the site…</p>}
      {info.isError && (
        <p role="alert" className="text-destructive">
          The site did not answer: {info.error.message}
        </p>
      )}
      {info.data && <SiteFacts info={info.data} />}
      <div>
        <Button variant="outline" onClick={() => info.refetch()}>
          Ask again
        </Button>
      </div>
    </main>
  );
}
