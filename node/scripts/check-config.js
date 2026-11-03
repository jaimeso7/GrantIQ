import { configuration } from '../config.js';

// Safe to run from a host console: report only operational settings, never secrets
// or connection strings. Database reachability is checked by the running /health route.
try {
  const config = configuration();
  console.log(
    JSON.stringify(
      {
        valid: true,
        production: config.production,
        bind: config.host,
        port: config.port,
        allowedHosts: config.allowedHosts,
        storage: config.databaseUrl ? 'PostgreSQL' : 'local SQLite',
        scheduler: config.scheduler,
      },
      null,
      2,
    ),
  );
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
