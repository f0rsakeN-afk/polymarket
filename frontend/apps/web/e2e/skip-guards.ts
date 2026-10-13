/**
 * Whether the browser suite should skip.
 *
 * Extracted rather than inlined because the inlined version was wrong and
 * nothing noticed: `!process.env.REDIS_PASSWORD`, which reads an *empty* string
 * as "not configured". CI runs a passwordless Redis, so that guard satisfied
 * itself and the entire suite skipped - reported as a clean green run having
 * measured nothing, which is the only reason a regression here could reach
 * `main` with a checkmark beside it.
 *
 * The distinction that matters: a variable set to `""` is a *value the operator
 * chose*. Only `undefined` means nobody supplied it.
 */

/** True when the harness cannot reach Redis, so frames cannot be published. */
export function redisUnreachable(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.REDIS_PASSWORD === undefined
}

/** True when a required id is missing. An empty id is as useless as an absent one. */
export function missingId(value: string | undefined): boolean {
  return !value
}

/**
 * The full guard for a browser spec that needs both a seeded subject and Redis.
 */
export function shouldSkip(
  env: NodeJS.ProcessEnv,
  ...ids: Array<string | undefined>
): boolean {
  return redisUnreachable(env) || ids.some(missingId)
}