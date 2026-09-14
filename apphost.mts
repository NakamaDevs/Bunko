import { basename, dirname } from 'node:path';
import { createBuilder, EndpointProperty } from './.aspire/modules/aspire.mjs';

const required = (name: string) => {
  const value = process.env[name];
  if (!value) throw new Error(`Run this AppHost through bunko: missing ${name}`);
  return value;
};
const config = required('BUNKO_CONFIG');
const root = required('BUNKO_ROOT');
const state = required('BUNKO_STATE');
const databasePath = required('BUNKO_DATABASE');
const domain = required('BUNKO_DOMAIN');
const port = Number(required('BUNKO_PORT'));
const dev = process.env.BUNKO_DEV_TOOLS === '1';
const notesUiPort = process.env.BUNKO_NOTES_UI_PORT ?? '0';
const builder = await createBuilder();
const database = await builder.addDuckDB('annotations', {
  databasePath: dirname(databasePath), databaseFileName: basename(databasePath),
});
const python = (name: string, script: string, externalPort?: number) => builder.addPythonApp(name, './tools', script)
  .withUv({ install: false })
  .withEnvironment('BUNKO_CONFIG', config)
  .withEnvironment('BUNKO_ROOT', root)
  .withEnvironment('BUNKO_STATE', state)
  .withEnvironment('BUNKO_DEV_TOOLS', dev ? '1' : '0')
  .withHttpEndpoint({ name: 'http', env: 'PORT', ...(externalPort ? { port: externalPort } : {}) });
const notes = await python('notes', 'docs/annotations/service.py')
  .withReference(database).withEnvironment('BUNKO_DATABASE', databasePath)
  .withEnvironment('NOTES_UI_PORT', notesUiPort)
  .withHttpHealthCheck({ endpointName: 'http', path: '/notes' });
const api = await python('review-api', 'review/api/service.py')
  .withHttpHealthCheck({ endpointName: 'http', path: '/api/health' });
const docs = await python('docs', 'docs/serve.py')
  .withHttpHealthCheck({ endpointName: 'http', path: '/' });
const review = dev
  ? await builder.addExecutable('review-web', 'npm', './tools/review/web', ['run', 'dev'])
    .withEnvironment('BUNKO_DOMAIN', domain).withEnvironment('BUNKO_PORT', String(port))
    .withEnvironment('BUNKO_STATE', state).withEnvironment('BUNKO_ROOT', root)
    .withEnvironment('BUNKO_CONFIG', config)
    .withHttpEndpoint({ name: 'http', env: 'PORT' })
    .withHttpHealthCheck({ endpointName: 'http', path: '/' })
  : await python('review-web', 'review/static.py')
    .withHttpHealthCheck({ endpointName: 'http', path: '/' });
await python('gateway', 'gateway/service.py', port)
  .withEnvironment('NOTES_URL', notes.getEndpoint('http').property(EndpointProperty.Url))
  .withEnvironment('REVIEW_API_URL', api.getEndpoint('http').property(EndpointProperty.Url))
  .withEnvironment('REVIEW_WEB_URL', review.getEndpoint('http').property(EndpointProperty.Url))
  .withEnvironment('DOCS_URL', docs.getEndpoint('http').property(EndpointProperty.Url))
  .withEnvironment('BUNKO_DOMAIN', domain)
  .withHttpHealthCheck({ endpointName: 'http', path: '/health' })
  .waitFor(notes).waitFor(api).waitFor(docs).waitFor(review);
await builder.build().run();
