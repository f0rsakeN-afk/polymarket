import { nextJsConfig } from "@workspace/eslint-config/next-js"

/** @type {import("eslint").Linter.Config} */
export default [
  ...nextJsConfig,
  {
    // Playwright specs are not React.
    //
    // The React rules fire on them anyway and produce errors that describe
    // nothing real: a Playwright fixture named `use` is not a hook, and the
    // destructuring every worker-scoped fixture requires trips `no-empty-pattern`.
    // Turning the React-specific rules off here is honest - these files render
    // nothing and call no hooks - rather than a suppression wrapped around a real
    // problem.
    files: ["e2e/**"],
    rules: {
      "react-hooks/rules-of-hooks": "off",
      "react-hooks/exhaustive-deps": "off",
      "no-empty-pattern": "off",
    },
  },
]
