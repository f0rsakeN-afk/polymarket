import type { SVGProps } from "react"

/**
 * Question-mark icons.
 *
 * Hand-rolled rather than pulled from `lucide-react` so the glyph matches the
 * rest of the icon set: lucide's question mark has a flat base stroke, and
 * this one keeps the rounded terminals the rest of the icons use.
 */

type IconProps = SVGProps<SVGSVGElement> & {
  size?: number
  className?: string
}

export const QuestionMark = ({
  size = 20,
  className,
  ...props
}: IconProps) => (
  <svg
    data-lucide="question-mark"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    className={className}
    {...props}
  >
    <path
      d="M9 12l2 2 4-4m6.2-7.2a3 3 0 1 1-5.4 5.4L15 12l-3.2 3.2"
    />
  </svg>
)

export const CircleQuestionMark = ({
  size = 20,
  className,
  ...props
}: IconProps) => (
  <svg
    data-lucide="circle-question-mark"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    className={className}
    {...props}
  >
    <circle cx="12" cy="12" r="10" />
    <path
      d="M9 12l2 2 4-4m6.2-7.2a3 3 0 1 1-5.4 5.4L15 12l-3.2 3.2"
    />
  </svg>
)
