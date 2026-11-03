// Public-safe explanation: do not serve ignored staff documents from disk.
export function registerOverviewRoutes(app, { send }) {
  app.get('/sprint-review', (req, res) =>
    send(
      req,
      res,
      'GrantIQ on Node.js',
      `<section class="panel"><h2>How the application works</h2><p>Organization profile + research keywords → recurring source discovery → eligibility checks → explainable matching → persistent database → staff pipeline.</p><p>The Node.js runtime uses Express, PostgreSQL for hosting, and optional local MiniLM through Transformers.js. No Python process is required.</p><p>Hosted setup uses shared staff sign-in. Individual accounts and roles are future work. Follow RAILWAY.md (or SITEGROUND.md) in the repository for deployment and validation.</p><p><a href="/sources">Show actual search status</a> · <a href="/pipeline">Show the team pipeline</a></p></section>`,
    ),
  );
}
