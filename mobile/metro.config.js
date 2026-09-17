const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

// `shared/` holds the chat core the phone and the desktop connector both run:
// the execute socket and the log→conversation fold. Metro only watches the
// project root by default, so a file outside it resolves at build time and
// then fails to reload — the folder has to be declared.
const workspace = path.resolve(__dirname, '..');
const config = getDefaultConfig(__dirname);
config.watchFolders = [path.resolve(workspace, 'shared')];

module.exports = config;
