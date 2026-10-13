import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const target = join(root, 'web', 'dist');
await mkdir(target, { recursive: true });
// 仅生成静态React入口和Tailwind样式，继续由现有FastAPI提供页面与API。
await build({ entryPoints: [join(root, 'frontend', 'main.jsx')], outfile: join(target, 'main.js'),
  bundle: true, format: 'esm', minify: true, jsx: 'automatic', target: 'es2022',
  external: ['/assets/*'],
  define: { 'process.env.NODE_ENV': '"production"' }, legalComments: 'eof' });
execFileSync(process.execPath, [join(root, 'node_modules', 'tailwindcss', 'lib', 'cli.js'),
  '-c', join(root, 'tailwind.config.js'), '-i', join(root, 'frontend', 'index.css'),
  '-o', join(target, 'main.css'), '--minify'], { cwd: root, stdio: 'inherit' });
const notices = [];
for (const name of ['react', 'react-dom', 'lucide-react']) {
  const folder = join(root, 'node_modules', name);
  const manifest = JSON.parse(await readFile(join(folder, 'package.json'), 'utf8'));
  notices.push(`${name} ${manifest.version}\n${await readFile(join(folder, 'LICENSE'), 'utf8')}`);
}
await writeFile(join(target, 'THIRD_PARTY_LICENSES.txt'), notices.join('\n\n-----\n\n'), 'utf8');
console.log('React、Tailwind与Lucide前端已构建。');
