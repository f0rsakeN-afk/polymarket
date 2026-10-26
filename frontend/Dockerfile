FROM oven/bun:1.3.14-slim AS deps

WORKDIR /app

COPY package.json bun.lock turbo.json .npmrc ./
# Every workspace needs its manifest present before a frozen install, or bun
# resolves a different tree than the lockfile describes. A new workspace added
# here but not above fails the build with a lockfile error that reads like a
# corrupt lock rather than a missing line in this file. `bun.lock` and both
# Dockerfiles are checked against the workspaces on disk by
# `backend/tests/test_docker_workspace_manifests.py`.
COPY apps/web/package.json ./apps/web/
COPY apps/admin/package.json ./apps/admin/
COPY packages/ui/package.json ./packages/ui/
COPY packages/api-client/package.json ./packages/api-client/
COPY packages/schemas/package.json ./packages/schemas/
COPY packages/eslint-config/package.json ./packages/eslint-config/
COPY packages/typescript-config/package.json ./packages/typescript-config/

RUN bun install --frozen-lockfile

# ---------------------------------------------------------------------------

FROM oven/bun:1.3.14-slim AS builder

WORKDIR /app

COPY package.json bun.lock turbo.json tsconfig.json .npmrc ./
COPY apps/web/ ./apps/web/
COPY apps/admin/ ./apps/admin/
COPY packages/ ./packages/

# The workspace install goes LAST, deliberately.
#
# `COPY apps/web/ ./apps/web/` merges the build context into a tree that already
# holds the installed `node_modules`. Where a developer's `node_modules` reaches
# the context, the context wins — most visibly `apps/web/node_modules/next`, whose
# symlink points at whatever version that machine happens to have. The build then
# succeeds and produces an image from packages nobody declared, which is the worst
# kind of failure: reproducible-looking and silently wrong.
#
# `.dockerignore` is supposed to stop that, and ordering does not depend on it —
# which matters, because builds have been observed on this machine where the
# ignore file was not applied at all.
#
# Ordering also caches better: a source edit invalidates the COPY above, and this
# layer still hits cache because the deps stage has not changed.
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=deps /app/apps/admin/node_modules ./apps/admin/node_modules
COPY --from=deps /app/packages ./packages

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
# Where the admin gate sends a non-admin. Defaults to the API origin, which is
# correct for most deployments; set it when the storefront lives elsewhere.
ARG NEXT_PUBLIC_SITE_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL} \
    NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL} \
    NODE_ENV=production

# Both apps build in one image layer. They are separate deployables that happen
# to share a base image, which is the shape that keeps one `bun install` and one
# set of package versions - two images would be free to drift apart, and the
# shared API transport is exactly the code that must not.
RUN bunx turbo build --filter=web --filter=admin

# ---------------------------------------------------------------------------

FROM oven/bun:1.3.14-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && echo "nextjs:x:1001:1001::/home/nextjs:/bin/sh" >> /etc/passwd \
    && echo "nextjs:x:1001:" >> /etc/group \
    && mkdir -p /home/nextjs && chown -R nextjs:nextjs /home/nextjs

# Two apps, one image.
#
# The builder runs `turbo build --filter=web --filter=admin`, and until now the
# runner copied only web's output — so the admin app was compiled on every build
# and then thrown away, and the image contained nothing that could serve it.
#
# Each app gets its own root rather than sharing one, because Next's `standalone`
# output is monorepo-nested and *identical in shape* for both: `apps/<name>/server.js`
# plus its own `node_modules` and `package.json`. Merged into a single directory,
# the second copy overwrites the first.
#
# One image, two services. The build is the expensive part and the two apps are
# always released together; the runtime is scaled, restarted and taken down
# independently, which is what actually matters for an operator tool.

COPY --from=builder --chown=nextjs:nextjs /app/apps/web/.next/standalone ./web
COPY --from=builder --chown=nextjs:nextjs /app/apps/web/.next/static ./web/apps/web/.next/static
COPY --from=builder --chown=nextjs:nextjs /app/apps/web/public ./web/apps/web/public

COPY --from=builder --chown=nextjs:nextjs /app/apps/admin/.next/standalone ./admin
COPY --from=builder --chown=nextjs:nextjs /app/apps/admin/.next/static ./admin/apps/admin/.next/static
# `public/` is currently empty (a .gitkeep), which is why the COPY exists at all:
# Docker has no optional-COPY, so a missing directory fails the build rather than
# being skipped. It is here so the first real asset - the admin favicon, which
# does not exist yet - does not need a build change to ship.
COPY --from=builder --chown=nextjs:nextjs /app/apps/admin/public ./admin/apps/admin/public

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0

USER nextjs

# Overridden per service: `admin` sets PORT=3001 and a different WORKDIR. The
# default is the storefront, so a bare `docker run` of this image does something
# sensible rather than serving an operator tool on the consumer's port.
ENV PORT=3000

WORKDIR /app/web/apps/web

EXPOSE 3000 3001

# Uses ${PORT} rather than a literal, so the `admin` service health-checks 3001
# instead of quietly polling the wrong app's home page - which answers 200 and
# makes the check pass while the service is not serving at all.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:${PORT}/ || exit 1

CMD ["node", "server.js"]
