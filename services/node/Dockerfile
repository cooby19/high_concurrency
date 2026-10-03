FROM node:22.14.0-bookworm-slim
WORKDIR /app
COPY server.js .
RUN node -p "JSON.stringify(process.versions)" > /build-info.txt
ENV NODE_ENV=production
CMD ["node", "server.js"]
