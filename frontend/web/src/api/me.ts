import { useQuery } from "@tanstack/react-query";

import { apiFetchJson } from "./client";
import { MeSchema } from "../types/dto";

export function useMeQuery(enabled: boolean) {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => apiFetchJson("/me", { schema: MeSchema }),
    enabled
  });
}

