FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_TRIAGE_API_URL=http://localhost:8080
ENV NEXT_PUBLIC_TRIAGE_API_URL=$NEXT_PUBLIC_TRIAGE_API_URL
RUN npm run build

FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32
ENV NODE_ENV=production
WORKDIR /app
RUN addgroup -S triage && adduser -S triage -G triage
COPY --from=build --chown=triage:triage /app ./
USER triage
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--host", "0.0.0.0", "--port", "3000"]
