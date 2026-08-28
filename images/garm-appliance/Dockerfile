# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=docker.io/node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43
ARG GO_IMAGE=docker.io/golang:1.26.2-alpine@sha256:f85330846cde1e57ca9ec309382da3b8e6ae3ab943d2739500e08c86393a21b1
ARG STOCK_IMAGE=ghcr.io/cloudbase/garm@sha256:5ccdc29c31084ed4f30ec85e09a57b5105cf3dcc5fa8c1aba9e68de461e7e635

FROM ${NODE_IMAGE} AS webapp
ARG GARM_SHA
RUN apk add --no-cache git
RUN set -eux; \
    git init /build/garm; \
    git -C /build/garm remote add origin https://github.com/SemperSupra/garm.git; \
    git -C /build/garm fetch --depth=1 origin "${GARM_SHA}"; \
    git -C /build/garm checkout --detach FETCH_HEAD; \
    test "$(git -C /build/garm rev-parse HEAD)" = "${GARM_SHA}"
WORKDIR /build/garm/webapp
RUN npm ci && npm run build

FROM ${GO_IMAGE} AS builder
ARG GARM_SHA
ARG GARM_VERSION
ARG TRUENAS_PROVIDER_SHA
RUN apk add --no-cache musl-dev gcc libtool m4 autoconf g++ make libblkid util-linux-dev git linux-headers
COPY --from=webapp /build/garm /build/garm
RUN set -eux; \
    rm -rf /build/garm/webapp/assets/_app /build/garm/webapp/assets/assets /build/garm/webapp/assets/index.html /build/garm/webapp/assets/*.png; \
    cp -r /build/garm/webapp/build/* /build/garm/webapp/assets/; \
    cd /build/garm; \
    CGO_ENABLED=1 go build -trimpath -buildvcs=false \
      -tags osusergo,netgo,sqlite_omit_load_extension \
      -ldflags "-linkmode external -extldflags '-static' -s -w -X github.com/cloudbase/garm/util/appdefaults.Version=${GARM_VERSION}" \
      -o /out/garm ./cmd/garm; \
    CGO_ENABLED=1 go build -trimpath -buildvcs=false \
      -tags osusergo,netgo,sqlite_omit_load_extension \
      -ldflags "-linkmode external -extldflags '-static' -s -w -X github.com/cloudbase/garm/util/appdefaults.Version=${GARM_VERSION}" \
      -o /out/garm-cli ./cmd/garm-cli
RUN set -eux; \
    git init /build/garm-provider-truenas; \
    git -C /build/garm-provider-truenas remote add origin https://github.com/SemperSupra/garm-provider-truenas.git; \
    git -C /build/garm-provider-truenas fetch --depth=1 origin "${TRUENAS_PROVIDER_SHA}"; \
    git -C /build/garm-provider-truenas checkout --detach FETCH_HEAD; \
    test "$(git -C /build/garm-provider-truenas rev-parse HEAD)" = "${TRUENAS_PROVIDER_SHA}"; \
    cd /build/garm-provider-truenas; \
    CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags "-s -w" \
      -o /out/garm-provider-truenas ./cmd/garm-provider-truenas

FROM ${STOCK_IMAGE} AS runtime
ARG GARM_SHA
ARG TRUENAS_PROVIDER_SHA
ARG FOUNDRY_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/SemperSupra/truenas-app-foundry" \
      org.opencontainers.image.description="SemperSupra GARM appliance for TrueNAS" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.sempersupra.garm.source-revision="${GARM_SHA}" \
      io.sempersupra.garm-provider-truenas.source-revision="${TRUENAS_PROVIDER_SHA}" \
      io.sempersupra.foundry.source-revision="${FOUNDRY_SHA}"
COPY --from=builder /out/garm /bin/garm
COPY --from=builder /out/garm-cli /bin/garm-cli
COPY --from=builder /out/garm-provider-truenas /opt/garm/providers.d/garm-provider-truenas
ENTRYPOINT ["/bin/garm", "--config", "/etc/garm/config.toml"]
