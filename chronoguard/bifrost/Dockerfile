FROM golang:1.26.1-bookworm@sha256:ab3d6955bbc813a0f3fdf220c1d817dd89c0b3f283777db8ece4a32fe7858edd AS build
ENV GOTOOLCHAIN=local
WORKDIR /src
COPY bifrost/upstream.lock bifrost/integration.patch /src/
RUN --mount=type=bind,from=upstream_source,target=/pinned <<'SH'
set -eu
tr -d '\r' < /src/upstream.lock > /tmp/upstream.lock
source_dir=/src/.upstream/bifrost
mkdir -p "$source_dir"
cd "$source_dir"
repo="$(sed -n '1p' /tmp/upstream.lock)"
revision="$(sed -n '2p' /tmp/upstream.lock)"
archive="/pinned/bifrost-$revision.tar.gz"
if [ -f "$archive" ]; then
  tar -xzf "$archive" --strip-components=1
else
  git init -q
  git remote add origin "$repo"
  git config remote.origin.promisor true
  git config remote.origin.partialclonefilter blob:none
  git config http.lowSpeedLimit 1024
  git config http.lowSpeedTime 30
  git sparse-checkout set --cone $(tail -n +3 /tmp/upstream.lock)
  git -c http.version=HTTP/1.1 fetch --filter=blob:none --depth=1 origin "$revision"
  git checkout --detach FETCH_HEAD
fi
sed -i 's/\r$//' framework/logstore/tables.go plugins/semanticcache/main.go \
  transports/bifrost-http/lib/config.go transports/bifrost-http/server/plugins.go
git apply --ignore-whitespace /src/integration.patch
tail -n +3 /tmp/upstream.lock | while IFS= read -r module; do
  sed -i 's/\r$//; s/^go 1\.27\.3$/go 1.26.0/' "$module/go.mod"
done
mkdir -p transports/bifrost-http/ui
echo '<title>Bifrost for ChronoGuard</title>' > transports/bifrost-http/ui/index.html
SH
COPY bifrost/plugins/chronoguard ./chronoguard/bifrost/plugins/chronoguard
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build <<'SH'
set -eu
cd /src/.upstream/bifrost
go work init ../../chronoguard/bifrost/plugins/chronoguard
tail -n +3 /tmp/upstream.lock | while IFS= read -r module; do
  if [ "$module" != "transports" ]; then
    name="$(sed -n 's/^module //p' "$module/go.mod")"
    (cd transports && GOWORK=off go mod edit "-replace=$name=../$module")
  fi
  go work use "./$module"
done
cd transports
GOWORK=off go mod edit -replace=github.com/chronoguard/chronoguard=../../../chronoguard/bifrost/plugins/chronoguard
mkdir -p /out
go build -trimpath -o /out/bifrost ./bifrost-http
SH

FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /out/bifrost /usr/local/bin/bifrost
COPY --chown=10002:10002 bifrost/config.json /etc/bifrost/config.json
RUN chown 10002:10002 /etc/bifrost
USER 10002
EXPOSE 8002
ENTRYPOINT ["bifrost", "-host", "0.0.0.0", "-port", "8002", "-app-dir", "/etc/bifrost"]
