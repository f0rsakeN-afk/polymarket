// API hooks barrel — comment exports only to avoid conflicts
// use-markets exports: useMarkets, useMarket, useMarketActivity, useGlobalTrades, useMarketTrades, useComments, usePostComment, useEditComment, useDeleteComment, useFAQs, useRelatedMarkets, useCreateMarket, useResolveMarket, usePriceHistory, useMarketCategories, useClaimWinnings
// use-trades exports: useSimpleGlobalTrades, useSimpleMarketTrades
// use-comments exports: useComments, useCommentReplies, usePostComment, useEditComment, useDeleteComment
// use-orders exports: useOrders, usePlaceOrder, useCancelOrder
// use-wallet exports: useWallet, useTransactions, useDeposit, useWithdraw
// use-positions exports: usePositions
// use-notifications exports: useNotifications, useNotificationPreferences, useUpdateNotificationPreferences, useMarkNotificationRead, useMarkAllNotificationsRead
// use-alerts exports: useAlerts, useCreateAlert, useDeleteAlert
// use-disputes exports: useDisputesForMarket, useCreateDispute, useProposeResolution, useAdjudicateDispute
// use-flags exports: useFlagsForMarket, useCreateFlag, useResolveFlag
// use-liquidity exports: useLPAnalytics, useLPPosition
// use-split-merge exports: useSplit, useMerge
// use-referrals exports: useReferralCode, useReferralStats
// use-treasury exports: useTreasury, useTreasuryLogs
// use-auth exports: useCurrentUser, useLogin, useLogout, useLogoutAll, useSessions, useRevokeSession, useRegister, useVerifyEmail, useResendVerification, useSendMagicLink, useVerifyMagicCode, useRequestMagicUrl, useVerifyMagicUrl, useForgotPassword, useResetPassword, useSetPassword, useChangePassword, useTwoFactorStatus, useTwoFactorSetup, useTwoFactorEnable, useTwoFactorDisable

// ─── Auth ──────────────────────────────────────────────────────────────────────
export { useCurrentUser, useLogin, useLogout, useLogoutAll, useSessions, useRevokeSession, useRegister, useVerifyEmail, useResendVerification, useSendMagicLink, useVerifyMagicCode, useRequestMagicUrl, useVerifyMagicUrl, useForgotPassword, useResetPassword, useSetPassword, useChangePassword, useTwoFactorStatus, useTwoFactorSetup, useTwoFactorEnable, useTwoFactorDisable } from "./api/use-auth"

// ─── Markets (infinite queries) ───────────────────────────────────────────────
export { useMarkets, useMarket, useMarketActivity, useFAQs, useRelatedMarkets, useCreateMarket, useResolveMarket, usePriceHistory, useMarketCategories, useClaimWinnings, useOrderBook } from "./api/use-markets"
export { useMarketTrades, useGlobalTrades } from "./api/use-markets"

// ─── Comments ─────────────────────────────────────────────────────────────────
export { useComments, useCommentReplies, usePostComment, useEditComment, useDeleteComment } from "./api/use-comments"

// ─── Orders ───────────────────────────────────────────────────────────────────
export { useOrders, usePlaceOrder, useCancelOrder } from "./api/use-orders"

// ─── Wallet ───────────────────────────────────────────────────────────────────
export { useWallet, useTransactions, useDeposit, useWithdraw } from "./api/use-wallet"

// ─── Positions ────────────────────────────────────────────────────────────────
export { usePositions } from "./api/use-positions"

// ─── Trades (simple queries) ─────────────────────────────────────────────────
export { useSimpleGlobalTrades, useSimpleMarketTrades } from "./api/use-trades"

// ─── Notifications ───────────────────────────────────────────────────────────
export { useNotifications, useNotificationPreferences, useUpdateNotificationPreferences, useMarkNotificationRead, useMarkAllNotificationsRead } from "./api/use-notifications"

// ─── Alerts ───────────────────────────────────────────────────────────────
export { useAlerts, useCreateAlert, useDeleteAlert } from "./api/use-alerts"

// ─── Disputes ──────────────────────────────────────────────────────────────
export { useDisputesForMarket, useCreateDispute, useProposeResolution, useAdjudicateDispute } from "./api/use-disputes"

// ─── Flags ───────────────────────────────────────────────────────────────
export { useFlagsForMarket, useCreateFlag, useResolveFlag } from "./api/use-flags"

// ─── Liquidity ──────────────────────────────────────────────────────────
export { useLPAnalytics, useLPPosition } from "./api/use-liquidity"

// ─── Split/Merge ────────────────────────────────────────────────────────
export { useSplit, useMerge } from "./api/use-split-merge"

// ─── Referrals ───────────────────────────────────────────────────────────
export { useReferralCode, useReferralStats } from "./api/use-referrals"

// ─── Treasury ───────────────────────────────────────────────────────────
export { useTreasury, useTreasuryLogs } from "./api/use-treasury"

// ─── Root-level hooks (infrastructure) ────────────────────────────────────
export { AuthProvider, useAuth } from "./use-auth-context"
export { useMarketSocket } from "./use-market-socket"
export { useUserSocket } from "./use-user-socket"
export { useCarouselScroll } from "./use-carousel-scroll"
