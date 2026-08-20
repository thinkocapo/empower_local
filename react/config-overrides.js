const SentryWebpackPlugin = require('@sentry/webpack-plugin');
const reactsourceMapPlugin = require('@acemarke/react-prod-sourcemaps');

module.exports = function override(config, env) {
  // Emit a canonical source map alongside the build.
  config.plugins.push(
    reactsourceMapPlugin.WebpackReactSourcemapsPlugin({
      mode: 'strict',
    })
  );

  // Upload source maps to Sentry ONLY when an auth token is provided.
  // Set SENTRY_AUTH_TOKEN, SENTRY_ORG, and REACT_SENTRY_PROJECT in your .env
  // to enable readable stack traces. With no token, the build still succeeds
  // (source maps just aren't uploaded).
  if (process.env.SENTRY_AUTH_TOKEN) {
    config.plugins.push(
      SentryWebpackPlugin.sentryWebpackPlugin({
        authToken: process.env.SENTRY_AUTH_TOKEN,
        org: process.env.SENTRY_ORG,
        project: process.env.REACT_SENTRY_PROJECT,
        release: {
          name: process.env.REACT_APP_RELEASE,
        },
      })
    );
  } else {
    console.log(
      '[config-overrides] SENTRY_AUTH_TOKEN not set — skipping source map upload.'
    );
  }

  return config;
};
