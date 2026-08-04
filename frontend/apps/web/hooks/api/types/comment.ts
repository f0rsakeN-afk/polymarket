export interface Comment {
  id: string
  user_id: string
  username: string
  content: string
  depth: number
  parent_id: string | null
  reply_count: number
  is_deleted: boolean
  created_at: string
}

export interface CommentsResponse {
  success: boolean
  data: {
    comments: Comment[]
    page: number
    page_size: number
  }
}
