import { z } from "zod"

export const listPositionsSchema = z.object({
  page: z.number().int().positive().optional(),
  page_size: z.number().int().positive().max(100).optional(),
})

export type ListPositionsInput = z.infer<typeof listPositionsSchema>
