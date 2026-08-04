import { z } from "zod"

export const listMarketsSchema = z.object({
  q: z.string().optional(),
  category: z.string().optional(),
  status: z.string().optional(),
  page: z.number().int().positive().optional(),
  page_size: z.number().int().positive().max(100).optional(),
})

export const postCommentSchema = z.object({
  content: z.string().min(1).max(2000),
  parent_id: z.string().nullable().optional(),
})

export const updateCommentSchema = z.object({
  content: z.string().min(1).max(2000),
})

export const resolveMarketSchema = z.object({
  winning_outcome_id: z.string(),
})

export type ListMarketsInput = z.infer<typeof listMarketsSchema>
export type PostCommentInput = z.infer<typeof postCommentSchema>
export type UpdateCommentInput = z.infer<typeof updateCommentSchema>
export type ResolveMarketInput = z.infer<typeof resolveMarketSchema>
