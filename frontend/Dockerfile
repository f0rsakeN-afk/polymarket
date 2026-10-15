FROM oven/bun:1.4-slim AS deps

WORKDIR /app

COPY package.json bun.lock turbo.json .npmrc ./
# Every workspace needs its manifest present before a frozen install, or bun
# resolves a different tree than the lockfile describes. A new workspace added
# here but not above fails the build with a lockfile error that reads like a
# corrupt lock rather than a missing line in this file.
COPY apps/web/package.json ./apps/web/
COPY apps/admin/package.json ./apps/admin/
COPY packages/ui/package.json ./packages/ui/
COPY packages/api-client/package.json ./packages/api-client/
COPY packages/eslint-config/package.json ./packages/eslint-config/
COPY packages/typescript-config/package.json ./packages/typescript-config/

RUN bun install --frozen-lockfile

# ---------------------------------------------------------------------------

FROM oven/bun:1.4-slim AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=deps /app/apps/admin/node_modules ./apps/admin/node_modules
COPY --from=deps /app/packages ./packages

COPY package.json bun.lock turbo.json tsconfig.json .npmrc ./
COPY apps/web/ ./apps/web/
COPY apps/admin/ ./apps/admin/
COPY packages/ ./packages/

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

FROM oven/bun:1.4-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && echo "nextjs:x:1001:1001::/home/nextjs:/bin/sh" >> /etc/passwd \
    && echo "nextjs:x:1001:" >> /etc/group \
    && mkdir -p /home/nextjs && chown -R nextjs:nextjs /home/nextjs

COPY --from=builder --chown=nextjs:nextjs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nextjs /app/apps/web/public ./apps/web/public

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:3000/ || exit 1

USER nextjs

WORKDIR /app/apps/web

CMD ["node", "server.js"]
