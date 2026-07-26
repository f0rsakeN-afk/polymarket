"use client"

import { useCallback, memo, useState } from "react"
import { useForm } from "react-hook-form"
import { valibotResolver } from "@hookform/resolvers/valibot"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Field,
  FieldContent,
  FieldError,
} from "@workspace/ui/components/field"
import { cn } from "@workspace/ui/lib/utils"
import { useComments, usePostComment } from "@/hooks/use-markets"
import { sileo } from "sileo"
import { object, pipe, string, minLength, maxLength } from "valibot"
import { getMarketCommentReplies } from "@/lib/api/markets"

const CommentSchema = object({
  content: pipe(string(), minLength(1, "Comment cannot be empty"), maxLength(2000, "Max 2000 characters")),
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
}: {
  comment: { id: string; username: string; content: string; created_at: string; depth: number; reply_count?: number }
  slug: string
}) {
  const [replies, setReplies] = useState<typeof comment[]>([])
  const [showReplies, setShowReplies] = useState(false)
  const [loadingReplies, setLoadingReplies] = useState(false)

  const loadReplies = useCallback(async () => {
    setLoadingReplies(true)
    try {
      const res = await getMarketCommentReplies(slug, comment.id)
      setReplies(res.data.replies)
    } catch {}
    setLoadingReplies(false)
  }, [slug, comment.id])

  const toggleReplies = useCallback(async () => {
    if (!showReplies && replies.length === 0) {
      await loadReplies()
    }
    setShowReplies((v) => !v)
  }, [showReplies, replies.length, loadReplies])

  return (
    <div className={cn("py-3", comment.depth > 0 && "ml-6 border-l-2 border-border pl-3")}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-semibold text-foreground">{comment.username}</span>
        <span className="text-[10px] text-muted-foreground">{timeAgo(comment.created_at)}</span>
        {(comment.reply_count ?? 0) > 0 && (
          <button
            onClick={toggleReplies}
            className="ml-auto text-[10px] text-primary hover:text-primary/80 font-medium transition-colors"
          >
            {loadingReplies ? "..." : showReplies ? "Hide replies" : `${comment.reply_count} replies`}
          </button>
        )}
      </div>
      <p className="text-xs leading-relaxed text-foreground">{comment.content}</p>
      {showReplies && replies.map((r) => (
        <CommentRow key={r.id} comment={r} slug={slug} />
      ))}
    </div>
  )
})

function CommentForm({ slug }: { slug: string }) {
  const { mutateAsync: postComment, isPending } = usePostComment(slug)

  const { register, handleSubmit, reset, formState: { errors } } = useForm<CommentInput>({
    resolver: valibotResolver(CommentSchema),
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

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex gap-2">
      <Field className="flex-1">
        <FieldContent>
          <Input
            placeholder="Add a comment..."
            className="h-7"
            {...register("content")}
          />
        </FieldContent>
        {errors.content && (
          <FieldError errors={[{ message: errors.content.message }]} />
        )}
      </Field>
      <Button type="submit" size="sm" disabled={isPending}>
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
    <div className="divide-y divide-border overflow-y-auto max-h-64 scrollbar-hide">
      {comments.map((comment) => (
        <CommentRow key={comment.id} comment={comment} slug={slug} />
      ))}
    </div>
  )
}

export { CommentList, CommentForm }
