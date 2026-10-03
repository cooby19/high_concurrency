# syntax=docker/dockerfile:1
# Use the official SDK archive so builds do not depend on MCR's regional CDN.
FROM buildpack-deps:bookworm-curl AS build
WORKDIR /src
RUN --mount=type=secret,id=proxy_ca if [ -f /run/secrets/proxy_ca ]; then export CURL_CA_BUNDLE=/run/secrets/proxy_ca; fi; \
    curl --fail -o /tmp/sdk.tar.gz https://builds.dotnet.microsoft.com/dotnet/Sdk/9.0.203/dotnet-sdk-9.0.203-linux-x64.tar.gz && \
    mkdir /dotnet && tar -xzf /tmp/sdk.tar.gz -C /dotnet && rm /tmp/sdk.tar.gz
ENV DOTNET_ROOT=/dotnet PATH=/dotnet:$PATH DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 DOTNET_CLI_TELEMETRY_OPTOUT=1
COPY . .
RUN dotnet publish -c Release -o /out && dotnet --info > /out/build-info.txt
FROM debian:bookworm-slim
ENV DOTNET_ROOT=/dotnet PATH=/dotnet:$PATH DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
WORKDIR /app
COPY --from=build /dotnet/dotnet /dotnet/dotnet
COPY --from=build /dotnet/host /dotnet/host
COPY --from=build /dotnet/shared /dotnet/shared
COPY --from=build /out .
COPY --from=build /out/build-info.txt /build-info.txt
CMD ["dotnet", "Server.dll"]
