import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import { usePrivileges } from "@/app/privileges";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePerPage } from "@/library/perPage";
import { BATCH } from "@/library/posts";
import { ShareLinkRow } from "@/post/ShareLinks";

export function AccountShareLinks({ user }: { user: string }) {
  const auth = useAuth();
  const can = usePrivileges();
  if (!auth.user || !can?.("shareLinks:list:self")) return null;
  return (
    <section aria-label="Share links">
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Share links</CardTitle>
        </CardHeader>
        <CardContent>
          <UserShareLinks key={user} user={user} />
        </CardContent>
      </Card>
    </section>
  );
}

function UserShareLinks({ user }: { user: string }) {
  const [perPage] = usePerPage();
  // Use the library batch size when its preference is auto-loading.
  const size = perPage === "auto" ? BATCH : perPage;
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: ["share-links", "user", user, offset],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/user/{user_name}/share-links", {
          params: { path: { user_name: user }, query: { offset, limit: size } },
          signal,
        }),
      ),
  });
  useEffect(() => {
    if (
      offset > 0 &&
      list.isSuccess &&
      !list.isFetching &&
      !list.data.results?.length
    ) {
      setOffset((current) => Math.max(0, current - size));
    }
  }, [offset, size, list.isSuccess, list.isFetching, list.data]);
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {list.isError ? <ApiErrorMessage error={list.error} /> : null}
      {list.isPending ? <p>Loading share links…</p> : null}
      {list.isSuccess && !list.data.results?.length ? <p>No share links.</p> : null}
      <ul aria-label="Your share links" className="flex flex-col gap-3">
        {list.data?.results?.map((link) => (
          <ShareLinkRow
            key={link.id}
            link={link}
            header={
              <Link
                to="/posts/$id"
                params={{ id: String(link.postId) }}
                className="text-link hover:underline"
              >
                Post {link.postId}
              </Link>
            }
          />
        ))}
      </ul>
      <nav aria-label="Share link pages" className="flex gap-2">
        <Button
          variant="outline"
          disabled={offset === 0 || list.isFetching}
          onClick={() => setOffset(Math.max(0, offset - size))}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          disabled={
            !list.data || offset + size >= (list.data.total ?? 0) || list.isFetching
          }
          onClick={() => setOffset(offset + size)}
        >
          Next
        </Button>
      </nav>
    </div>
  );
}
