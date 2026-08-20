FROM node:20-bookworm-slim

RUN npm install -g serve

WORKDIR /src

# Build-time configuration. create-react-app inlines every REACT_APP_* var into
# the bundle at build time, so these must be ARGs (not runtime env). The Sentry
# source-map upload vars are optional — the build succeeds without them.
ARG REACT_APP_DSN
ARG REACT_APP_RELEASE=empower-local-react@1.0.0
ARG REACT_APP_ENVIRONMENT=local
ARG REACT_APP_BACKEND_URL_FLASK=http://localhost:8080
ARG REACT_APP_SPOTLIGHT=false
ARG SENTRY_AUTH_TOKEN=
ARG SENTRY_ORG=
ARG REACT_SENTRY_PROJECT=

ENV REACT_APP_DSN=$REACT_APP_DSN \
    REACT_APP_RELEASE=$REACT_APP_RELEASE \
    REACT_APP_ENVIRONMENT=$REACT_APP_ENVIRONMENT \
    REACT_APP_BACKEND_URL_FLASK=$REACT_APP_BACKEND_URL_FLASK \
    REACT_APP_SPOTLIGHT=$REACT_APP_SPOTLIGHT \
    SENTRY_AUTH_TOKEN=$SENTRY_AUTH_TOKEN \
    SENTRY_ORG=$SENTRY_ORG \
    REACT_SENTRY_PROJECT=$REACT_SENTRY_PROJECT

COPY package.json package-lock.json ./
RUN npm install

COPY . .
RUN npm run build

EXPOSE 3000
CMD ["serve", "-s", "build", "-l", "3000"]
