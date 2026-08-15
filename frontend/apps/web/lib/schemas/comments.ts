import { z } from "zod"

export const postCommentSchema = z.object({
  content: z.string().min(1).max(2000),
  parent_id: z.string().nullable().optional(),
})

export const updateCommentSchema = z.object({
  content: z.string().min(1).max(2000),
})

export const commentResponseSchema = z.object({
  id: z.string(),
  market_id: z.string(),
  user_id: z.string(),
  username: z.string(),
  parent_id: z.string().nullable(),
  content: z.string(),
  depth: z.number().int().min(0),
  is_deleted: z.boolean(),
  reply_count: z.number().int().min(0),
  created_at: z.string(),
  updated_at: z.string(),
})

export const commentListResponseSchema = z.object({
  comments: z.array(commentResponseSchema),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
})

export const commentRepliesResponseSchema = z.object({
  replies: z.array(commentResponseSchema),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
})

export type PostCommentInput = z.infer<typeof postCommentSchema>
export type UpdateCommentInput = z.infer<typeof updateCommentSchema>
export type CommentResponse = z.infer<typeof commentResponseSchema>
export type CommentListResponse = z.infer<typeof commentListResponseSchema>
export type CommentRepliesResponse = z.infer<typeof commentRepliesResponseSchema>
