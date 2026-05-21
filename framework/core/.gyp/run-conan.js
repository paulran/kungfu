// SPDX-License-Identifier: Apache-2.0

const fse = require('fs-extra');
const path = require('path');
const { shell } = require('../lib');

function conan(cmd) {
  shell.run('conan', cmd, true, {
    env: { NODE_GYP_RUN: 'on', ...process.env },
  });
}

function getNodeVersionOptions() {
  const packageJson = fse.readJsonSync(
    path.resolve(path.dirname(__dirname), 'package.json'),
  );
  const electronVersion = packageJson.devDependencies['electron'];
  const nodeVersion = packageJson.devDependencies['@kungfu-trader/libnode'];
  return [
    '-o',
    `electron_version=${electronVersion.replace('^', '')}`,
    '-o',
    `node_version=${nodeVersion}`,
    '-o',
    'with_yarn=True',
    '-o',
    'vs_toolset=v143',
    '-o',
    'log_level=info',
    '-o',
    'arch=x64',
    '-o',
    'freezer=pyinstaller',
  ];
}

function makeConanSetting(name) {
  return ['-s', `${name}=${shell.getConfigValue(name)}`];
}

function makeConanSettings(names) {
  return names.map(makeConanSetting).flat();
}

function makeConanOption(name) {
  return ['-o', `${name}=${shell.getConfigValue(name)}`];
}

function makeConanOptions(names) {
  return names.map(makeConanOption).flat().concat(getNodeVersionOptions());
}

function conanInstall() {
  const settings = makeConanSettings(['build_type']);
  const options = makeConanOptions(['arch', 'log_level', 'freezer']);
  conan([
    'install',
    '.',
    '-of',
    'build',
    '--build',
    'missing',
    ...settings,
    ...options,
  ]);
}

function conanBuild() {
  const settings = makeConanSettings(['build_type']);
  const options = getNodeVersionOptions();
  conan(['build', '.', '-of', 'build', ...settings, ...options]);
}

function conanPackage() {
  const conanSettings = makeConanSettings(['build_type']);
  const options = getNodeVersionOptions();
  conan([
    'package',
    '.',
    '-of',
    'build',
    '-pf',
    path.join('dist', 'kfc'),
    ...conanSettings,
    ...options,
  ]);
}

const cli = require('sywac')
  .command('install', {
    run: conanInstall,
  })
  .command('build', {
    run: conanBuild,
  })
  .command('package', {
    run: conanPackage,
  })
  .help('--help')
  .version('--version')
  .showHelpByDefault();

async function main() {
  await cli.parseAndExit();
}

module.exports.cli = cli;
module.exports.main = main;

if (require.main === module) main().catch(shell.utils.exitOnError);
