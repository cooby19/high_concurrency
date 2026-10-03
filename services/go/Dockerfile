FROM golang:1.24.1-bookworm AS build
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /server . && go version > /build-info.txt
FROM debian:bookworm-slim
COPY --from=build /server /server
COPY --from=build /build-info.txt /build-info.txt
CMD ["/server"]
