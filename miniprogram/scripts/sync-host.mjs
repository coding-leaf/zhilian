/**
 * Cross-platform sync of the built mini-program into the WeChat DevTools host directory.
 *
 * Target resolution:
 *   - Windows  -> D:\zhilian-mp
 *   - WSL/Linux -> /mnt/d/zhilian-mp
 *   - Override with env ZHILIAN_MP_TARGET.
 *
 * Mirrors the CONTENTS of dist/build/mp-weixin into the target directory.
 */
import { cp, mkdir, readdir } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const source = path.resolve('dist/build/mp-weixin');
const defaultTarget = os.platform() === 'win32' ? 'D:\\zhilian-mp' : '/mnt/d/zhilian-mp';
const target = process.env.ZHILIAN_MP_TARGET || defaultTarget;

await mkdir(target, { recursive: true });

const entries = await readdir(source);
for (const entry of entries) {
  await cp(path.join(source, entry), path.join(target, entry), {
    recursive: true,
    force: true,
  });
}

console.log(`==> Successfully synced to ${target}`);
