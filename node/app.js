import express from 'express';
import path from 'node:path';
import { root } from './config.js';
import { security } from './security.js';
import { createRouteContext } from './routes/context.js';
import { registerErrorRoutes } from './routes/errors.js';
import { registerAuthRoutes } from './routes/auth.js';
import { registerGrantsRoutes } from './routes/grants.js';
import { registerSettingsRoutes } from './routes/settings.js';
import { registerSourcesRoutes } from './routes/sources.js';
import { registerResearchRoutes } from './routes/research.js';
import { registerVerificationRoutes } from './routes/verification.js';
import { registerExportRoutes } from './routes/export.js';
import { registerOverviewRoutes } from './routes/overview.js';

/**
 * Compose HTTP middleware and feature routes. Importing this module never opens
 * a listener or starts discovery, so tests can exercise routes independently.
 */
export function createApp(store, config, discovery) {
  const app = express();
  app.set('query parser', 'simple');
  app.use(express.urlencoded({ extended: false, limit: '256kb', parameterLimit: 500 }));
  // Authentication, host checks and CSRF run before every feature route.
  const sessions = security(app, config);
  app.use(
    '/static',
    express.static(path.join(root, 'node/public'), { dotfiles: 'deny', index: false }),
  );
  app.use(async (req, res, next) => {
    // Do not reveal the private organization profile on the public sign-in page.
    if (
      (!config.password || req.session.auth) &&
      !req.path.startsWith('/api/') &&
      req.path !== '/health'
    )
      res.locals.organization = (await store.read()).profile.name;
    next();
  });
  const context = createRouteContext(store, config, discovery, sessions);
  registerAuthRoutes(app, context);
  registerGrantsRoutes(app, context);
  registerSettingsRoutes(app, context);
  registerSourcesRoutes(app, context);
  registerResearchRoutes(app, context);
  registerVerificationRoutes(app, context);
  registerExportRoutes(app, context);
  registerOverviewRoutes(app, context);
  registerErrorRoutes(app);
  return app;
}
