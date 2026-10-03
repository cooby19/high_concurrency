# syntax=docker/dockerfile:1
FROM rust:1.90.0-bookworm AS build
WORKDIR /src
COPY . .
RUN --mount=type=secret,id=proxy_ca if [ -f /run/secrets/proxy_ca ]; then export CARGO_HTTP_CAINFO=/run/secrets/proxy_ca; fi; cargo build --release --locked && rustc --version > /build-info.txt && cargo tree --locked --offline >> /build-info.txt
FROM debian:bookworm-slim
COPY --from=build /src/target/release/hc-server /server
COPY --from=build /build-info.txt /build-info.txt
CMD ["/server"]
