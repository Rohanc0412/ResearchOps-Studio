import { z } from "zod";
import { useQuery } from "@tanstack/react-query";

import { apiFetchJson } from "./client";

export const MfaStatusSchema = z
  .object({
    enabled: z.boolean(),
    pending: z.boolean().optional()
  })
  .passthrough();

export type MfaStatus = z.infer<typeof MfaStatusSchema>;

export const MfaEnrollStartSchema = z
  .object({
    secret: z.string().min(1),
    otpauth_uri: z.string().min(1),
    issuer: z.string().min(1),
    account_name: z.string().min(1),
    period: z.number().int().min(1),
    digits: z.number().int().min(4)
  })
  .passthrough();

export type MfaEnrollStart = z.infer<typeof MfaEnrollStartSchema>;

export const MfaToggleSchema = z
  .object({
    enabled: z.boolean()
  })
  .passthrough();

export type MfaToggle = z.infer<typeof MfaToggleSchema>;

export function useMfaStatusQuery(enabled: boolean) {
  return useQuery({
    queryKey: ["mfa-status"],
    queryFn: async () => apiFetchJson("/auth/mfa/status", { schema: MfaStatusSchema }),
    enabled
  });
}

export async function startMfaEnroll(): Promise<MfaEnrollStart> {
  return apiFetchJson("/auth/mfa/enroll/start", {
    method: "POST",
    schema: MfaEnrollStartSchema
  });
}

export async function verifyMfaEnroll(code: string): Promise<MfaToggle> {
  return apiFetchJson("/auth/mfa/enroll/verify", {
    method: "POST",
    body: { code },
    schema: MfaToggleSchema
  });
}

export async function disableMfa(code: string): Promise<MfaToggle> {
  return apiFetchJson("/auth/mfa/disable", {
    method: "POST",
    body: { code },
    schema: MfaToggleSchema
  });
}
