/**
 * Where "go to the site" should point.
 *
 * ## Why this is not just `config.siteUrl`
 *
 * `config.siteUrl` falls back to the **API origin** when `NEXT_PUBLIC_SITE_URL`
 * is unset. For the storefront app that is a harmless guess — it is the same
 * deployment in production. Here it is actively wrong: the admin panel is a
 * separate app, and an operator who follows "go to the site" and lands on the
 * API's JSON root has been sent somewhere with no links on it.
 *
 * ## Why it is not a bare path either
 *
 * `/` on the admin origin is this app's own root, and this proxy sends
 * non-admins back to `/login`. A relative fallback is therefore a redirect loop
 * wearing a link's clothing.
 *
 * So: an absolute URL or nothing. A caller with no configured storefront should
 * render no link rather than a wrong one, and this returns `null` so that is a
 * decision rather than an accident.
 */
import { config } from "@workspace/api-client/config"

export function storefrontUrl(): string | null {
  const candidate = (config.siteUrl ?? "").trim()
  return /^https?:\/\//i.test(candidate) ? candidate : null
}