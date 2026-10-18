// The CLI loads mermaid.esm.mjs, not the external-dependency core entry. Rebuild
// that browser entry from the published core and our audited, locked libraries;
// changing node_modules alone leaves upstream's embedded sanitizer unchanged.
import { build, version as compilerVersion } from 'esbuild';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = '/opt/mermaid';
const hash = path => createHash('sha256').update(readFileSync(resolve(root, path))).digest('hex');
const metadata = name => JSON.parse(readFileSync(`${root}/node_modules/${name}/package.json`, 'utf8'));
const result = await build({
  absWorkingDir: root,
  entryPoints: { 'mermaid.esm': 'node_modules/mermaid/dist/mermaid.core.mjs' },
  outdir: 'node_modules/mermaid/dist',
  outExtension: { '.js': '.mjs' },
  chunkNames: 'chunks/diavisuals/[name]-[hash]',
  bundle: true,
  splitting: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  sourcemap: 'external',
  metafile: true,
});
const inputs = Object.keys(result.metafile.inputs);
for (const name of ['dompurify', 'katex']) {
  if (!inputs.some(path => path.startsWith(`node_modules/${name}/`))) {
    throw new Error(`browser bundle did not consume the locked ${name} dependency`);
  }
}
if (inputs.some(path => /chunks\/mermaid\.esm/.test(path))) {
  throw new Error('browser build consumed an upstream pre-bundled dependency');
}
const receipt = {
  profile: 'diavisuals-mermaid-browser-build-v1',
  compiler: { name: 'esbuild', version: compilerVersion },
  versions: Object.fromEntries(['mermaid', 'dompurify', 'katex'].map(name => [name, metadata(name).version])),
  lock_sha256: hash('package-lock.json'),
  inputs: inputs.map(path => ({ path, sha256: hash(path) })),
  outputs: Object.keys(result.metafile.outputs).map(path => ({ path, sha256: hash(path) })),
};
writeFileSync(`${root}/browser-build.json`, `${JSON.stringify(receipt, null, 2)}\n`);
