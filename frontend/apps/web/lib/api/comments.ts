import { api } from "./client"
import type { CommentsResponse, Comment } from "../types/api"

export function getMarketComments(
  slug: string,
  params?: { page?: number; page_size?: number }
) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<CommentsResponse>(
    `/api/v1/markets/${slug}/comments${query ? `?${query}` : ""}`
  )
}

export function getMarketCommentReplies(
  slug: string,
  commentId: string,
  params?: { page?: number; page_size?: number }
) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<{ success: boolean; data: { replies: Comment[]; page: number; page_size: number } }>(
    `/api/v1/markets/${slug}/comments/${commentId}/replies${query ? `?${query}` : ""}`
  )
}

export function postComment(
  slug: string,
  content: string,
  parent_id?: string
) {
  return api.post<{ success: boolean; data: Comment }>(
    `/api/v1/markets/${slug}/comments`,
    { content, parent_id: parent_id ?? null }
  )
}

export function updateComment(
  slug: string,
  commentId: string,
  content: string
) {
  return api.patch<{ success: boolean; data: { id: string; content: string; updated_at: string } }>(
    `/api/v1/markets/${slug}/comments/${commentId}`,
    { content }
  )
}

export function deleteComment(slug: string, commentId: string) {
  return api.delete<{ success: boolean; data: { id: string; status: string } }>(
    `/api/v1/markets/${slug}/comments/${commentId}`
  )
}
