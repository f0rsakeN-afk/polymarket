/**
 * Canonical auth types live in `lib/api/auth.ts` (they mirror
 * `backend/app/api/auth.py`). This file only re-exports them so older
 * `@/hooks/api/types/user` imports cannot drift from the real contract.
 */
export type { MeResponse, Session } from "@/lib/api/auth";
