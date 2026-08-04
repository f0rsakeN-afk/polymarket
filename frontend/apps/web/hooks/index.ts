// API hooks - re-exported individually to avoid duplicate export conflicts
// (useComments/useMarketTrades etc. exist in multiple files)
export {
  useMarkets,
  useMarket,
  useMarketActivity,
  // useMarketTrades intentionally omitted - prefer the one from use-trades.ts
  useGlobalTrades,
  useComments,
  usePostComment,
  useEditComment,
  useDeleteComment,
  useFAQs,
  useRelatedMarkets,
  useCreateMarket,
  useResolveMarket,
  usePriceHistory,
  useMarketCategories,
} from "./api/use-markets"

export {
  useOrders,
  usePlaceOrder,
  useCancelOrder,
} from "./api/use-orders"

export {
  usePositions,
} from "./api/use-positions"

export {
  useWallet,
  useTransactions,
  useDeposit,
  useWithdraw,
} from "./api/use-wallet"

export {
  useGlobalTrades as useGlobalTradesFromTrades,
  useMarketTrades,
} from "./api/use-trades"

export {
  useLPAnalytics,
} from "./api/use-liquidity"

export {
  useNotifications,
  useNotificationPreferences,
  useUpdateNotificationPreferences,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
} from "./api/use-notifications"

export {
  useReferralCode,
  useReferralStats,
} from "./api/use-referrals"

export {
  useComments as useCommentsFromHook,
  useCommentReplies,
  usePostComment as usePostCommentFromHook,
  useEditComment as useEditCommentFromHook,
  useDeleteComment as useDeleteCommentFromHook,
} from "./api/use-comments"

export {
  useAlerts,
  useCreateAlert,
  useDeleteAlert,
} from "./api/use-alerts"

// Root-level hooks (infrastructure)
export { AuthProvider, useAuth } from "./use-auth-context"
export { useCurrentUser } from "./use-auth"
export { useMarketSocket } from "./use-market-socket"
export { useUserSocket } from "./use-user-socket"
export { useCarouselScroll } from "./use-carousel-scroll"
