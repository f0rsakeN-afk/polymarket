import { config } from "@/lib/config"
import { api, ApiError, markSessionEnded } from "./client"
import type { MutationResponse } from "@/lib/api/client"

/**
 * Types mirror `backend/app/api/account.py` response payloads.
 *
 * Money arrives as strings on purpose. The backend serialises `Decimal` as a
 * string because `float()` rounds money; parsing it into a JS number here would
 * put the rounding back, and a user comparing an exported balance against their
 * ledger would conclude the books were wrong.
 */

/** `GET /api/v1/account/deletion-impact` → data. */
export interface DeletionImpact {
  can_delete: boolean
  open_orders: number
  unsettled_positions: number
  /** Named rather than implied, so the UI can say what is kept up front. */
  retained_even_after_deletion: string[]
  blocked_detail: {
    open_orders: number
    unsettled_positions: number
    message: string
  } | null
}

/** `DELETE /api/v1/account` → data. */
export interface DeletionSummary {
  erased: Record<string, unknown>
  retained: { tables: string[]; reason: string }
}

/**
 * The export is fetched as a blob rather than through `api`, which parses JSON.
 *
 * Two reasons it must not go through the normal path. A large export is a
 * multi-megabyte string that does not belong inside the SPA's React tree, and the
 * response is an attachment - routing it through JSON parsing would hand the
 * user a blob in a textarea instead of a file.
 */
export async function downloadAccountExport(): Promise<void> {
  const res = await fetch(`${config.apiUrl}/api/v1/account/export`, {
    credentials: "include",
  })

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new ApiError(
      (data as { error?: string }).error ?? "Could not build your export",
      res.status,
      data,
      (data as { error_code?: string }).error_code
    )
  }

  const blob = await res.blob()

  // Honour the server's filename. It encodes the export date, which is the one
  // detail that makes a downloaded file identifiable later.
  const disposition = res.headers.get("content-disposition") ?? ""
  const match = /filename="?([^";]+)"?/.exec(disposition)
  const filename = match?.[1] ?? "predictx-export.json"

  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Revoking immediately can cancel the download in some browsers; one frame is
  // the shortest delay that is reliably after the click has been handled.
  setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

export const accountApi = {
  deletionImpact: () =>
    api.get<{ success: boolean; data: DeletionImpact }>("/api/v1/account/deletion-impact"),

  /**
   * `.finally`, not `.then`: erasure ends the local session whether or not the
   * server confirmed it, and the server invalidates the cookies on the way out.
   * Leaving `sessionState` as "active" would have the app attempt a refresh
   * against cookies that no longer exist.
   */
  delete: (password: string, code?: string) =>
    api
      .delete<MutationResponse<DeletionSummary>>("/api/v1/account", {
        password,
        code,
      })
      .finally(markSessionEnded),
}