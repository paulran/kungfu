if (!process.env.CI) {
  const { shell } = require('./framework/core');
  const opts = { silent: true };
  shell.run('yarn', ['-s', 'sync'], true, opts);
}
