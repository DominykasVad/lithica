import { useParams, useRouter } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Where a post will be shown (5.4). Back returns to the place in the library. */
export function PostPlaceholder() {
  const { id } = useParams({ from: "/posts/$id" });
  const router = useRouter();
  return (
    <main className="mx-auto flex max-w-5xl flex-col items-start gap-4 p-6">
      <h1 className="font-semibold text-2xl">Post {id}</h1>
      <p className="text-muted-foreground">The post page is not built yet.</p>
      <Button variant="outline" onClick={() => router.history.back()}>
        <ArrowLeft />
        Back
      </Button>
    </main>
  );
}
