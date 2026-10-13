import { build } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const target = join(root, 'web', 'vendor');
await mkdir(target, { recursive: true });
// 保留已生成的静态资源，网站启动时无需Node或npm。
await build({ entryPoints: [join(root, 'scripts', 'web-vendor-entry.js')], outfile: join(target, 'markdown-vendor.js'),
  bundle: true, minify: true, format: 'esm', platform: 'browser', target: 'es2022', legalComments: 'eof' });
const licenses = [];
for (const [name, license] of [['marked', 'LICENSE'], ['highlight.js', 'LICENSE'], ['dompurify', 'LICENSE']]) {
  const manifest = JSON.parse(await readFile(join(root, 'node_modules', name, 'package.json'), 'utf8'));
  const content = await readFile(join(root, 'node_modules', name, license), 'utf8');
  licenses.push(`${name} ${manifest.version}\n${content}`);
}
await writeFile(join(target, 'THIRD_PARTY_LICENSES.txt'), licenses.join('\n\n-----\n\n'), 'utf8');
console.log('本地 Markdown、高亮和HTML净化资源已打包。');
