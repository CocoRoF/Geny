/**
 * The two Android edits `expo prebuild` cannot express, applied idempotently.
 *
 * `prebuild` regenerates `android/` from the config, so any change made by
 * hand is lost the next time someone runs it — silently, and usually noticed
 * as "why does the update install fail now". Both edits below only matter at
 * release time, so a silent loss would be found by a user rather than by CI.
 * They are therefore part of `prebuild`, not a note in a README:
 *
 * 1. versionCode/versionName derived from package.json. Android refuses an
 *    update whose versionCode did not increase, and the generated file
 *    hardcodes 1.
 * 2. A release signing config from the environment. Every release must use
 *    the SAME key or the install is refused as a conflicting package and the
 *    user has to uninstall first, losing their settings. The key lives in CI
 *    secrets — this repository is public.
 *
 * Run it twice and nothing changes.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const gradlePath = join(root, 'android', 'app', 'build.gradle');

const VERSION_BLOCK = `        // Derived from package.json so a release bumps one file.
        // versionCode must increase monotonically or Android refuses the
        // install over the previous version: M*1e6 + m*1e3 + p.
        def pkgFile = new File(project.projectDir, "../../package.json")
        def pkg = new groovy.json.JsonSlurper().parseText(pkgFile.text)
        def (vMajor, vMinor, vPatch) = pkg.version.tokenize('.').collect { it.toInteger() }
        versionCode vMajor * 1000000 + vMinor * 1000 + vPatch
        versionName pkg.version`;

const RELEASE_SIGNING = `        release {
            // The same key every release, or Android reports a conflicting
            // package and the user must uninstall first — losing their
            // settings. The real key is a CI secret; this repo is public.
            //
            // Without one (a local build, a fork) this falls back to the debug
            // key: the APK installs and runs, it just cannot update a
            // CI-signed install.
            def ksFile = System.getenv('ANDROID_KEYSTORE_FILE')
            if (ksFile != null && new File(ksFile).exists()) {
                storeFile file(ksFile)
                storePassword System.getenv('ANDROID_KEYSTORE_PASSWORD')
                keyAlias System.getenv('ANDROID_KEY_ALIAS')
                keyPassword System.getenv('ANDROID_KEY_PASSWORD') ?: System.getenv('ANDROID_KEYSTORE_PASSWORD')
            } else {
                storeFile file('debug.keystore')
                storePassword 'android'
                keyAlias 'androiddebugkey'
                keyPassword 'android'
            }
        }
    }`;

let gradle = readFileSync(gradlePath, 'utf8');
const before = gradle;

if (!gradle.includes('def pkgFile =')) {
  const version = /^\s*versionCode \d+\n\s*versionName "[^"]*"$/m;
  if (!version.test(gradle)) throw new Error('build.gradle: version lines not found — prebuild output changed');
  gradle = gradle.replace(version, VERSION_BLOCK);
}

if (!gradle.includes('signingConfigs.release')) {
  const closeSigning = /(signingConfigs \{[\s\S]*?keyPassword 'android'\n        \}\n)    \}/;
  if (!closeSigning.test(gradle)) throw new Error('build.gradle: signingConfigs block not found — prebuild output changed');
  gradle = gradle.replace(closeSigning, `$1${RELEASE_SIGNING}`);
  gradle = gradle.replace(
    /release \{\n(\s*)\/\/ Caution![\s\S]*?signingConfig signingConfigs\.debug/,
    'release {\n$1signingConfig signingConfigs.release',
  );
}

if (gradle === before) {
  console.log('android: already patched');
} else {
  writeFileSync(gradlePath, gradle);
  console.log('android: version + release signing wired');
}
