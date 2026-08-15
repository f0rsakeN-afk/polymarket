"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { getMarketComments, getMarketCommentReplies, postComment, updateComment, deleteComment } from "@/lib/api/comments"
import { sileo } from "sileo"

export function useComments(slug: string, params?: { page?: number; page_size?: number }) {
  return useQuery({
    queryKey: ["comments", slug, params],
    queryFn: () => getMarketComments(slug, params),
    select: (res) => res.data?.comments,
    enabled: !!slug,
  })
}

export function useCommentReplies(slug: string, commentId: string) {
  return useQuery({
    queryKey: ["comment-replies", slug, commentId],
    queryFn: () => getMarketCommentReplies(slug, commentId),
    select: (res) => res.data?.replies,
    enabled: !!slug && !!commentId,
  })
}

export function usePostComment(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ content, parent_id }: { content: string; parent_id?: string }) =>
      postComment(slug, content, parent_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["comments", slug] }),
    onError: (err) => sileo.error({ title: err instanceof Error ? err.message : "Failed to post comment" }),
  })
}

export function useEditComment(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ commentId, content }: { commentId: string; content: string }) =>
      updateComment(slug, commentId, content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["comments", slug] }),
    onError: (err) => sileo.error({ title: err instanceof Error ? err.message : "Failed to edit comment" }),
  })
}

export function useDeleteComment(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ commentId }: { commentId: string }) => deleteComment(slug, commentId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["comments", slug] }),
    onError: (err) => sileo.error({ title: err instanceof Error ? err.message : "Failed to delete comment" }),
  })
}
