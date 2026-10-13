import { describe, expect, it } from "vitest"
import { missingId, redisUnreachable, shouldSkip } from "../e2e/skip-guards"

/**
 * A skipped test and a passing test look identical in CI's exit code.
 *
 * `bunx playwright test` exits 0 when every test skipped. So the guard deciding
 * whether to skip is, in CI, indistinguishable from a suite that ran and passed
 * - which means a bug in the guard is a silent loss of coverage rather than a
 * red build.
 *
 * The bug that existed: `!process.env.REDIS_PASSWORD`. That treats an empty
 * string as unset, and an empty string is exactly what a passwordless Redis
 * supplies - so on CI, where Redis has no password, the guard skipped every
 * test in the suite and reported success.
 */

const env = (values: Record<string, string>) => values as NodeJS.ProcessEnv

describe("redisUnreachable", () => {
  it("treats an empty password as configured, not absent", () => {
    // The whole point. An operator who sets REDIS_PASSWORD="" has chosen a
    // passwordless Redis; that is a valid configuration, not a missing one.
    expect(redisUnreachable(env({ REDIS_PASSWORD: "" }))).toBe(false)
  })

  it("treats a real password as configured", () => {
    expect(redisUnreachable(env({ REDIS_PASSWORD: "hunter2" }))).toBe(false)
  })

  it("only skips when the variable is genuinely absent", () => {
    expect(redisUnreachable(env({}))).toBe(true)
    expect(redisUnreachable(env({ OTHER: "x" }))).toBe(true)
  })
})

describe("missingId", () => {
  it("treats an empty id as missing", () => {
    // Unlike the password, an empty id is useless in every configuration: there
    // is no "id-less but valid" state, so treating "" as present would be a
    // guard that passes while guaranteeing the test cannot work.
    expect(missingId("")).toBe(true)
    expect(missingId(undefined)).toBe(true)
    expect(missingId("85c8b7c0-5cc7-458f-9dc2-2387af961404")).toBe(false)
  })
})

describe("shouldSkip", () => {
  const id = "bdd1a187-81d1-4a99-b33f-f52b0a546321"

  it("runs with a passwordless Redis and all ids present - the CI case", () => {
    expect(shouldSkip(env({ REDIS_PASSWORD: "" }), id)).toBe(false)
  })

  it("skips when Redis is unreachable", () => {
    expect(shouldSkip(env({}), id)).toBe(true)
  })

  it("skips when any required id is missing", () => {
    expect(shouldSkip(env({ REDIS_PASSWORD: "" }), undefined)).toBe(true)
    expect(shouldSkip(env({ REDIS_PASSWORD: "" }), "")).toBe(true)
    expect(shouldSkip(env({ REDIS_PASSWORD: "" }), id, undefined)).toBe(true)
  })

  it("requires every id, not just the first", () => {
    expect(shouldSkip(env({ REDIS_PASSWORD: "" }), id, id)).toBe(false)
    expect(shouldSkip(env({ REDIS_PASSWORD: "" }), id, "")).toBe(true)
  })
})