import * as ui from '../views.js';

// Register last, after all feature routes.
export function registerErrorRoutes(app) {
  app.use((_req, res) =>
    res.status(404).send(ui.layout('Not found', '<p><a href="/">Return to GrantIQ</a></p>')),
  );
  app.use((error, req, res, _next) => {
    const message = error.issues
      ? error.issues.map((x) => `${x.path.join('.')}: ${x.message}`).join('; ')
      : error.message;
    const expected =
      error.name === 'ZodError' ||
      error.status ||
      !/(SQL|database|password authentication|connect ECONN)/i.test(message);
    console.error('Request failed:', error.name);
    res
      .status(error.status || 422)
      .send(
        ui.layout(
          'Unable to complete this action',
          `<section class="panel error"><p>${ui.esc(expected ? message : 'Storage unavailable. Contact the administrator.')}</p><p>Your previous saved data is retained. <a href="${ui.esc(req.path)}">Return to page</a></p></section>`,
          { token: req.session?.csrf },
        ),
      );
  });
}
