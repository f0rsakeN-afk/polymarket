"use client"

import { useCallback, memo, useState } from "react"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Field,
  FieldContent,
  FieldError,
} from "@workspace/ui/components/field"
import { cn } from "@workspace/ui/lib/utils"
import { useComments, usePostComment, useEditComment, useDeleteComment } from "@/hooks/api/use-comments"
import { useCurrentUser } from "@/hooks/use-auth"
import { sileo } from "sileo"
import { getMarketCommentReplies } from "@/lib/api/markets"
import type { Comment } from "@/hooks/api/types/comment"

const commentSchema = z.object({
  content: z.string().min(1, "Comment cannot be empty").max(2000, "Max 2000 characters"),
})

type CommentInput = { content: string }

function timeAgo(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

const CommentRow = memo(function CommentRow({
  comment,
  slug,
  depth = comment.depth,
}: {
  comment: Comment
  slug: string
  depth?: number
}) {
  const [replies, setReplies] = useState<Comment[]>([])
  const [showReplies, setShowReplies] = useState(false)
  const [loadingReplies, setLoadingReplies] = useState(false)
  const [showReplyForm, setShowReplyForm] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState(comment.content)
  const { mutateAsync: postReply, isPending: isReplying } = usePostComment(slug)
  const { mutateAsync: editComment, isPending: isEditing } = useEditComment(slug)
  const { mutateAsync: removeComment, isPending: isDeleting } = useDeleteComment(slug)
  const { data: currentUser } = useCurrentUser()
  const isOwn = currentUser?.id === comment.user_id

  const loadReplies = useCallback(async () => {
    setLoadingReplies(true)
    try {
      const res = await getMarketCommentReplies(slug, comment.id)
      setReplies(res.data.replies)
    } catch {
      sileo.error({ title: "Failed to load replies" })
    } finally {
      setLoadingReplies(false)
    }
  }, [slug, comment.id])

  const toggleReplies = useCallback(async () => {
    if (!showReplies && replies.length === 0) {
      await loadReplies()
    }
    setShowReplies((v) => !v)
  }, [showReplies, replies.length, loadReplies])

  const handleReply = useCallback(async (content: string) => {
    try {
      await postReply({ content, parent_id: comment.id })
      setShowReplyForm(false)
      await loadReplies()
      setShowReplies(true)
      sileo.success({ title: "Reply posted" })
    } catch {
      sileo.error({ title: "Failed to post reply" })
    }
  }, [comment.id, postReply, loadReplies])

  const handleEdit = useCallback(async () => {
    if (!editValue.trim()) return
    try {
      await editComment({ commentId: comment.id, content: editValue.trim() })
      setEditing(false)
      sileo.success({ title: "Comment updated" })
    } catch {
      sileo.error({ title: "Failed to update comment" })
    }
  }, [comment.id, editValue, editComment])

  const handleDelete = useCallback(async () => {
    try {
      await removeComment({ commentId: comment.id })
      sileo.success({ title: "Comment deleted" })
    } catch {
      sileo.error({ title: "Failed to delete comment" })
    }
  }, [comment.id, removeComment])

  if (comment.is_deleted) return null

  return (
    <div className={cn("py-3", depth > 0 && "ml-6 border-l-2 border-border pl-3")}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-semibold text-foreground">{comment.username}</span>
        <span className="text-[10px] text-muted-foreground">{timeAgo(comment.created_at)}</span>
        <div className="ml-auto flex items-center gap-2">
          {isOwn && !editing && (
            <>
              <button
                onClick={() => { setEditValue(comment.content); setEditing(true) }}
                aria-label="Edit comment"
                className="text-[10px] text-muted-foreground hover:text-foreground font-medium transition-colors"
              >
                Edit
              </button>
              <button
                onClick={handleDelete}
                disabled={isDeleting}
                aria-label="Delete comment"
                className="text-[10px] text-red-500 hover:text-red-400 font-medium transition-colors"
              >
                {isDeleting ? "..." : "Delete"}
              </button>
            </>
          )}
          {depth < 3 && (
            <button
              onClick={() => setShowReplyForm((v) => !v)}
              aria-label={showReplyForm ? "Cancel reply" : "Reply to comment"}
              className="text-[10px] text-muted-foreground hover:text-foreground font-medium transition-colors"
            >
              Reply
            </button>
          )}
          {comment.reply_count > 0 && (
            <button
              onClick={toggleReplies}
              aria-expanded={showReplies}
              aria-label={showReplies ? "Hide replies" : `Show ${comment.reply_count} ${comment.reply_count === 1 ? "reply" : "replies"}`}
              className="text-[10px] text-primary hover:text-primary/80 font-medium transition-colors"
            >
              {loadingReplies ? "..." : showReplies ? "Hide" : `${comment.reply_count} ${comment.reply_count === 1 ? "reply" : "replies"}`}
            </button>
          )}
        </div>
      </div>
      {editing ? (
        <div className="flex gap-2">
          <label htmlFor={`edit-${comment.id}`} className="sr-only">Edit comment</label>
          <Input
            id={`edit-${comment.id}`}
            className="h-7 text-xs flex-1"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleEdit() }
              if (e.key === "Escape") { setEditing(false); setEditValue(comment.content) }
            }}
          />
          <Button size="sm" className="h-7 text-xs" onClick={handleEdit} disabled={isEditing || !editValue.trim()}>
            {isEditing ? <Spinner className="size-3" /> : "Save"}
          </Button>
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => { setEditing(false); setEditValue(comment.content) }} disabled={isEditing}>
            Cancel
          </Button>
        </div>
      ) : (
        <p className="text-xs leading-relaxed text-foreground">{comment.content}</p>
      )}
      {showReplyForm && (
        <ReplyForm onReply={handleReply} isPending={isReplying} onCancel={() => setShowReplyForm(false)} />
      )}
      {showReplies && replies.map((r) => (
        <CommentRow key={r.id} comment={r} slug={slug} depth={depth + 1} />
      ))}
    </div>
  )
})

function ReplyForm({ onReply, isPending, onCancel }: {
  onReply: (content: string) => Promise<void>
  isPending: boolean
  onCancel: () => void
}) {
  const [value, setValue] = useState("")

  const handleSubmit = useCallback(async () => {
    if (!value.trim()) return
    await onReply(value.trim())
    setValue("")
  }, [value, onReply])

  return (
    <div className="mt-2 flex gap-2">
      <label htmlFor="reply-input" className="sr-only">Write a reply</label>
      <Input
        id="reply-input"
        placeholder="Write a reply..."
        className="h-7 text-xs"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            handleSubmit()
          }
          if (e.key === "Escape") onCancel()
        }}
      />
      <Button size="sm" className="h-7 text-xs" onClick={handleSubmit} disabled={isPending || !value.trim()}>
        {isPending ? <Spinner className="size-3" /> : "Reply"}
      </Button>
      <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onCancel} disabled={isPending}>
        Cancel
      </Button>
    </div>
  )
}

function CommentForm({ slug }: { slug: string }) {
  const { data: currentUser } = useCurrentUser()
  const { mutateAsync: postComment, isPending } = usePostComment(slug)

  const { register, handleSubmit, reset, formState: { errors } } = useForm<CommentInput>({
    resolver: zodResolver(commentSchema),
  })

  const onSubmit = useCallback(async (data: CommentInput) => {
    try {
      await postComment({ content: data.content, parent_id: undefined })
      sileo.success({ title: "Comment posted" })
      reset()
    } catch (e) {
      sileo.error({ title: "Failed to post", description: e instanceof Error ? e.message : "Unknown error" })
    }
  }, [postComment, reset])

  if (!currentUser) {
    return (
      <p className="text-xs text-muted-foreground">
        <Link href="/login" className="underline underline-offset-2 hover:text-foreground">Sign in</Link> to comment
      </p>
    )
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex gap-2" aria-label="Post a comment">
      <Field className="flex-1">
        <FieldContent>
          <Input
            id="comment-input"
            placeholder="Add a comment..."
            className="h-7"
            aria-describedby={errors.content ? "comment-error" : undefined}
            aria-invalid={!!errors.content}
            {...register("content")}
          />
        </FieldContent>
        {errors.content && (
          <FieldError id="comment-error" errors={[{ message: errors.content.message }]} />
        )}
      </Field>
      <Button type="submit" size="sm" disabled={isPending} aria-label="Post comment">
        {isPending ? <Spinner className="size-4" /> : "Post"}
      </Button>
    </form>
  )
}

function CommentList({ slug }: { slug: string }) {
  const { data: comments, isLoading, error } = useComments(slug)

  if (isLoading) {
    return (
      <div className="flex h-20 items-center justify-center">
        <Spinner className="size-5" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="py-6 text-center text-muted-foreground text-xs">
        An error occurred while fetching comments.
      </div>
    )
  }

  if (!comments || comments.length === 0) {
    return (
      <div className="py-8 text-center text-xs text-muted-foreground">No comments yet. Be the first to discuss!</div>
    )
  }

  return (
    <div className="divide-y divide-border overflow-y-auto max-h-64 scrollbar-hide" role="feed" aria-label="Comments" aria-live="polite">
      {comments.map((comment) => (
        <CommentRow key={comment.id} comment={comment} slug={slug} />
      ))}
    </div>
  )
}

export { CommentList, CommentForm }
