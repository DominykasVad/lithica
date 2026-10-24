import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import type { components } from "@/api/schema";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { CardsOnly } from "@/components/CardsOnly";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

/** How many posts are character cards: what the cards module adds here. */
function CardCount() {
  const cards = useQuery({
    queryKey: ["posts", "card-count"],
    queryFn: () =>
      unwrap(
        api.GET("/posts", {
          params: { query: { query: "card-spec:v1,v2,v3", limit: 1, fields: "id" } },
        }),
      ),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Character cards</CardTitle>
      </CardHeader>
      <CardContent>
        {cards.isError ? (
          <ApiErrorMessage error={cards.error} />
        ) : (
          <p>
            {cards.data ? `${cards.data.total ?? "?"} cards on this site` : "Counting…"}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** The start page, for now: what the site says about itself. */
export function Home() {
  const info = useQuery(infoQuery);

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <h1 className="font-semibold text-2xl">
        {info.data?.config?.name ?? "Sardonyx"}
      </h1>
      {info.isPending && <p>Asking the site…</p>}
      {info.isError && <ApiErrorMessage error={info.error} />}
      {info.data && <SiteFacts info={info.data} />}
      <CardsOnly>
        <CardCount />
      </CardsOnly>
      <div>
        <Button variant="outline" onClick={() => info.refetch()}>
          Ask again
        </Button>
      </div>
    </main>
  );
}
