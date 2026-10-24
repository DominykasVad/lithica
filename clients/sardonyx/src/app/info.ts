import { queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";

/** `GET /info`: the site, and the modules it has switched on. */
export const infoQuery = queryOptions({
  queryKey: ["info"],
  queryFn: async () => {
    const { data, error } = await api.GET("/info");
    if (error) {
      throw new Error(error.description);
    }
    return data;
  },
});
