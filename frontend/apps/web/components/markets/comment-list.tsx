"use client"

import { memo, useCallback, useState } from "react"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Textarea } from "@workspace/ui/components/textarea"
import { Spinner } from "@workspace/ui/components/spinner"
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

// ── Utilities ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  })
}

/** Stable color from username — seeded by first char, maps to a hue */
const DEPTH_COLORS = [
  "border-primary/40",
  "border-blue-400/40",
  "border-purple-400/40",
  "border-pink-400/40",
]

function Avatar({ username }: { username: string }) {
  const initials = username.slice(0, 2).toUpperCase()
  // Hue from first char — gives each user a consistent identity color
  const hue = username.charCodeAt(0) * 37 % 360
  return (
    <div
      className="size-7 shrink-0 rounded-full flex items-center justify-center text-[10px] font-bold text-white select-none"
      style={{ background: `hsl(${hue}, 55%, 45%)` }}
      aria-hidden="true"
    >
      {initials}
    </div>
  )
}

// ── Reply form ────────────────────────────────────────────────────────────────

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
    <div className="mt-2 flex flex-col gap-2 rounded-lg border border-border bg-muted/40 p-3">
      <Textarea
        placeholder="Write a reply..."
        className="min-h-[64px] resize-none text-xs"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { handleSubmit() }
          if (e.key === "Escape") onCancel()
        }}
      />
      <div className="flex items-center justify-end gap-2">
        <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onCancel} disabled={isPending}>Cancel</Button>
        <Button size="sm" className="h-7 text-xs" onClick={handleSubmit} disabled={isPending || !value.trim()}>
          {isPending ? <Spinner className="size-3" /> : "Reply"}
        </Button>
      </div>
    </div>
  )
}

// ── Edit form ─────────────────────────────────────────────────────────────────

function EditForm({ comment, onEdit, isPending, onCancel }: {
  comment: Comment
  onEdit: (content: string) => Promise<void>
  isPending: boolean
  onCancel: () => void
}) {
  const [value, setValue] = useState(comment.content)

  const handleSubmit = useCallback(async () => {
    if (!value.trim() || value === comment.content) return
    await onEdit(value.trim())
  }, [value, comment.content, onEdit])

  return (
    <div className="mt-1 flex flex-col gap-2">
      <Textarea
        className="min-h-[64px] resize-none text-xs"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { handleSubmit() }
          if (e.key === "Escape") onCancel()
        }}
      />
      <div className="flex items-center justify-end gap-2">
        <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onCancel} disabled={isPending}>Cancel</Button>
        <Button size="sm" className="h-7 text-xs" onClick={handleSubmit} disabled={isPending || !value.trim() || value === comment.content}>
          {isPending ? <Spinner className="size-3" /> : "Save"}
        </Button>
      </div>
    </div>
  )
}

// ── Comment row ───────────────────────────────────────────────────────────────

const CommentRow = memo(function CommentRow({
  comment,
  slug,
  depth = 0,
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
  const [liked, setLiked] = useState(false)
  const [likeCount, setLikeCount] = useState(0)
  const { mutateAsync: postReply } = usePostComment(slug)
  const { mutateAsync: editComment } = useEditComment(slug)
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

  const handleEdit = useCallback(async (content: string) => {
    try {
      await editComment({ commentId: comment.id, content })
      setEditing(false)
      sileo.success({ title: "Comment updated" })
    } catch {
      sileo.error({ title: "Failed to update comment" })
    }
  }, [comment.id, editComment])

  const handleDelete = useCallback(async () => {
    try {
      await removeComment({ commentId: comment.id })
      sileo.success({ title: "Comment deleted" })
    } catch {
      sileo.error({ title: "Failed to delete comment" })
    }
  }, [comment.id, removeComment])

  const handleLike = useCallback(() => {
    setLiked((v) => !v)
    setLikeCount((n) => liked ? n - 1 : n + 1)
  }, [liked])

  if (comment.is_deleted) {
    return (
      <div className={cn("py-2", depth > 0 && "ml-10 pl-3")}>
        <span className="text-[10px] italic text-muted-foreground">[deleted]</span>
      </div>
    )
  }

  const depthColor = DEPTH_COLORS[depth % DEPTH_COLORS.length]

  return (
    <div className={cn("group py-3", depth > 0 && "ml-10 pl-3 border-l-2 rounded-none", depthColor)}>
      <div className="flex gap-2.5">
        <Avatar username={comment.username} />
        <div className="flex-1 min-w-0">
          {/* Header row */}
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="text-xs font-semibold text-foreground leading-none">{comment.username}</span>
            <time
              dateTime={comment.created_at}
              title={formatDate(comment.created_at)}
              className="text-[10px] text-muted-foreground leading-none"
            >
              {timeAgo(comment.created_at)}
            </time>
            {comment.updated_at !== comment.created_at && (
              <span className="text-[9px] text-muted-foreground/60 leading-none">(edited)</span>
            )}
          </div>

          {/* Content */}
          {editing ? (
            <EditForm
              comment={comment}
              onEdit={handleEdit}
              isPending={false}
              onCancel={() => setEditing(false)}
            />
          ) : (
            <p className="text-xs leading-relaxed text-foreground whitespace-pre-wrap break-words">{comment.content}</p>
          )}

          {/* Actions row */}
          <div className="mt-1.5 flex items-center gap-3">
            <button
              onClick={handleLike}
              aria-label={liked ? "Unlike" : "Like"}
              aria-pressed={liked}
              className={cn(
                "flex items-center gap-1 text-[10px] font-medium transition-colors",
                liked ? "text-red-500" : "text-muted-foreground hover:text-red-400"
              )}
            >
              <HeartIcon filled={liked} className="size-3" />
              {likeCount > 0 && <span>{likeCount}</span>}
            </button>

            {depth < 3 && (
              <button
                onClick={() => setShowReplyForm((v) => !v)}
                className="text-[10px] text-muted-foreground hover:text-foreground font-medium transition-colors"
              >
                Reply
              </button>
            )}

            {isOwn && !editing && (
              <button
                onClick={() => { setEditing(true) }}
                className="text-[10px] text-muted-foreground hover:text-foreground font-medium transition-colors"
              >
                Edit
              </button>
            )}
            {isOwn && !editing && (
              <button
                onClick={handleDelete}
                disabled={isDeleting}
                className="text-[10px] text-muted-foreground hover:text-red-500 font-medium transition-colors disabled:opacity-50"
              >
                {isDeleting ? "..." : "Delete"}
              </button>
            )}

            {comment.reply_count > 0 && (
              <button
                onClick={toggleReplies}
                className="ml-auto flex items-center gap-1 text-[10px] text-primary hover:text-primary/80 font-medium transition-colors"
              >
                {loadingReplies ? (
                  <Spinner className="size-2.5" />
                ) : (
                  <ChevronIcon expanded={showReplies} className="size-2.5" />
                )}
                {showReplies ? "Hide" : `${comment.reply_count} ${comment.reply_count === 1 ? "reply" : "replies"}`}
              </button>
            )}
          </div>

          {/* Inline reply form */}
          {showReplyForm && (
            <ReplyForm
              onReply={handleReply}
              isPending={false}
              onCancel={() => setShowReplyForm(false)}
            />
          )}

          {/* Nested replies */}
          {showReplies && replies.map((r) => (
            <CommentRow key={r.id} comment={r} slug={slug} depth={depth + 1} />
          ))}
        </div>
      </div>
    </div>
  )
})

// ── Small inline icons ─────────────────────────────────────────────────────────

function HeartIcon({ filled, className }: { filled: boolean; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5">
      <path d="M8 13.5s-5.5-3.5-5.5-7A3.5 3.5 0 0 1 8 3a3.5 3.5 0 0 1 5.5 3.5c0 3.5-5.5 7-5.5 7z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function ChevronIcon({ expanded, className }: { expanded: boolean; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d={expanded ? "M2 8l4-4 4 4" : "M2 4l4 4 4-4"} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ── Comment composer ───────────────────────────────────────────────────────────

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
      <p className="text-xs text-muted-foreground py-2">
        <Link href="/login" className="underline underline-offset-2 hover:text-foreground font-medium">Sign in</Link> to join the discussion
      </p>
    )
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex gap-2 items-center" aria-label="Post a comment">
      <Avatar username={currentUser.username ?? "you"} />
      <Input
        {...register("content")}
        placeholder="Add a comment..."
        className="h-7 text-xs flex-1"
        aria-describedby={errors.content ? "comment-error" : undefined}
      />
      <Button type="submit" size="sm" disabled={isPending} className="h-7 text-xs shrink-0">
        {isPending ? <Spinner className="size-3" /> : "Post"}
      </Button>
    </form>
  )
}

// ── Comment list ──────────────────────────────────────────────────────────────

const CommentList = memo(function CommentList({ slug }: { slug: string }) {
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
      <div className="rounded-lg border border-border bg-card py-6 text-center text-xs text-muted-foreground">
        Failed to load comments.
      </div>
    )
  }

  if (!comments || comments.length === 0) {
    return (
      <div className="py-8 text-center space-y-1">
        <p className="text-xs font-medium text-muted-foreground">No comments yet</p>
        <p className="text-[10px] text-muted-foreground/60">Be the first to share your thoughts</p>
      </div>
    )
  }

  return (
    <div role="feed" aria-label="Comments" aria-live="polite">
      {comments.map((comment) => (
        <CommentRow key={comment.id} comment={comment} slug={slug} />
      ))}
    </div>
  )
})

export { CommentList, CommentForm }
