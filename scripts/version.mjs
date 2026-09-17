/**
 * One version for everything a user installs.
 *
 * The desktop connector and the mobile app are one product wearing two
 * packages, and they ship in one release. They drifted the moment they had
 * two package.json files and two tags — 0.23.0 and 0.1.0, two releases, two
 * answers to "which version am I on".
 *
 *   node scripts/version.mjs            → print the version (fails if they differ)
 *   node scripts/version.mjs 0.24.0     → set both
 *   node scripts/version.mjs --check    → exit 1 if they differ (CI gate)
 *
 * Android's versionCode is derived from this same string (M*1e6 + m*1e3 + p,
 * in mobile/android/app/build.gradle), so bumping here is the whole bump.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const PACKAGES = ['desktop', 'mobile'];

function read(name) {
  const path = join(root, name, 'package.json');
  return { path, json: JSON.parse(readFileSync(path, 'utf8')) };
}

function current() {
  const versions = PACKAGES.map((name) => [name, read(name).json.version]);
  const distinct = new Set(versions.map(([, v]) => v));
  if (distinct.size !== 1) {
    const listed = versions.map(([n, v]) => `${n}=${v}`).join(', ');
    throw new Error(
      `the apps are on different versions (${listed}). ` +
      `They ship in one release, so they must agree — run: node scripts/version.mjs <version>`,
    );
  }
  return versions[0][1];
}

const arg = process.argv[2];

if (!arg || arg === '--check') {
  try {
    const version = current();
    if (arg === '--check') console.log(`ok — both apps are ${version}`);
    else console.log(version);
  } catch (err) {
    console.error(String(err.message));
    process.exit(1);
  }
} else {
  if (!/^\d+\.\d+\.\d+$/.test(arg)) {
    console.error(`not a version: ${arg} (expected M.m.p)`);
    process.exit(1);
  }
  for (const name of PACKAGES) {
    const { path, json } = read(name);
    json.version = arg;
    writeFileSync(path, `${JSON.stringify(json, null, 2)}\n`);
    console.log(`${name}: ${arg}`);
  }
  // app.json carries the version Expo stamps into the native projects; the
  // Android build reads package.json, but iOS and the app listing read this.
  const appJsonPath = join(root, 'mobile', 'app.json');
  const appJson = JSON.parse(readFileSync(appJsonPath, 'utf8'));
  appJson.expo.version = arg;
  writeFileSync(appJsonPath, `${JSON.stringify(appJson, null, 2)}\n`);
  console.log(`mobile/app.json: ${arg}`);
}
