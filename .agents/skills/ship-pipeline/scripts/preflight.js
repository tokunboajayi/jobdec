#!/usr/bin/env node
/**
 * ship preflight — verify CLIs and env vars for a /ship stack before an
 * unattended run starts. Never prints secret values, only names.
 *
 * Usage:
 *   node <ship-pipeline skill dir>/scripts/preflight.js --list
 *   node <ship-pipeline skill dir>/scripts/preflight.js --stack <id> [--features a,b] [--env-file .env.local]
 *                                  [--local-only] [--json]
 *
 * Exit codes: 0 ready, 1 missing requirements, 2 usage error.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const DEFAULT_CONFIG = path.join(__dirname, '..', 'stacks.json');

function parseArgs(argv) {
  const args = { features: [], envFiles: [], localOnly: false, json: false, list: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = () => {
      const value = argv[++i];
      if (value === undefined) throw new Error(`${arg} needs a value`);
      return value;
    };
    if (arg === '--stack') args.stack = next();
    else if (arg === '--features') args.features = next().split(',').map(s => s.trim()).filter(Boolean);
    else if (arg === '--env-file') args.envFiles.push(next());
    else if (arg === '--config') args.config = next();
    else if (arg === '--local-only') args.localOnly = true;
    else if (arg === '--json') args.json = true;
    else if (arg === '--list') args.list = true;
    else if (arg === '-h' || arg === '--help') args.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  return args;
}

/** Parse KEY=VALUE lines. Values are only used for presence checks. */
function parseEnvFile(content) {
  const out = {};
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    out[match[1]] = value;
  }
  return out;
}

function commandExists(name) {
  if (!/^[A-Za-z0-9._-]+$/.test(name)) return false;
  const probe = process.platform === 'win32' ? 'where' : 'which';
  const result = spawnSync(probe, [name], { stdio: 'ignore' });
  return result.status === 0;
}

function isSet(env, name) {
  return typeof env[name] === 'string' && env[name].trim() !== '';
}

/**
 * Pure check. `env` is a name->value map, `hasCommand` a predicate.
 * Returns { ready, missingEnv: [[anyOf...]], missingCli: [[anyOf...]], optionalMissing: [] }.
 */
function check(config, { stack, features = [], localOnly = false, env = {}, hasCommand = commandExists }) {
  const profile = config.stacks[stack];
  if (!profile) throw new Error(`unknown stack "${stack}". Run --list to see stacks.`);

  const unknown = features.filter(f => !config.features[f]);
  if (unknown.length) throw new Error(`unknown feature(s): ${unknown.join(', ')}`);
  const unsupported = features.filter(f => !(profile.features || []).includes(f));
  if (unsupported.length) throw new Error(`stack "${stack}" does not support: ${unsupported.join(', ')}`);

  const cliGroups = [...(profile.cli || [])];
  const envGroups = [...(profile.env || [])];
  const optional = [];

  if (!localOnly && profile.deploy) {
    cliGroups.push(...(profile.deploy.cli || []));
    envGroups.push(...(profile.deploy.env || []));
  }
  for (const feature of features) {
    envGroups.push(...(config.features[feature].env || []));
    optional.push(...(config.features[feature].optionalEnv || []));
  }

  const missingCli = cliGroups.filter(group => !group.some(hasCommand));
  const missingEnv = envGroups.filter(group => !group.some(name => isSet(env, name)));
  const optionalMissing = optional.filter(name => !isSet(env, name));

  return { ready: missingCli.length === 0 && missingEnv.length === 0, missingCli, missingEnv, optionalMissing };
}

function formatReport(config, args, result) {
  const lines = [];
  const where = config.where || {};
  lines.push(`ship preflight: ${args.stack}${args.features.length ? ` + ${args.features.join(', ')}` : ''}${args.localOnly ? ' (local only)' : ''}`);
  if (result.ready) lines.push('READY - all required CLIs and env vars present.');
  for (const group of result.missingCli) lines.push(`MISSING CLI: ${group.join(' or ')}`);
  for (const group of result.missingEnv) {
    lines.push(`MISSING ENV: ${group.join(' or ')}`);
    const hint = where[group[0]];
    if (hint) lines.push(`  get it: ${hint}`);
  }
  for (const name of result.optionalMissing) {
    lines.push(`optional (not blocking): ${name}${where[name] ? ` - ${where[name]}` : ''}`);
  }
  return lines.join('\n');
}

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`ship-preflight: ${error.message}`);
    process.exit(2);
  }
  if (args.help) {
    console.log('Usage: preflight.js --list | --stack <id> [--features a,b] [--env-file f] [--local-only] [--json]');
    process.exit(0);
  }

  const config = JSON.parse(fs.readFileSync(args.config || DEFAULT_CONFIG, 'utf8'));

  if (args.list) {
    for (const [id, profile] of Object.entries(config.stacks)) {
      const mark = id === config.default ? ' (default)' : '';
      console.log(`${id}${mark}\n  ${profile.label}\n  best for: ${profile.bestFor}\n  features: ${(profile.features || []).join(', ') || 'none'}`);
    }
    process.exit(0);
  }
  if (!args.stack) args.stack = config.default;

  const env = { ...process.env };
  for (const file of args.envFiles) {
    if (fs.existsSync(file)) Object.assign(env, parseEnvFile(fs.readFileSync(file, 'utf8')));
  }

  let result;
  try {
    result = check(config, { stack: args.stack, features: args.features, localOnly: args.localOnly, env });
  } catch (error) {
    console.error(`ship-preflight: ${error.message}`);
    process.exit(2);
  }

  if (args.json) console.log(JSON.stringify({ stack: args.stack, features: args.features, ...result }, null, 2));
  else console.log(formatReport(config, args, result));
  process.exit(result.ready ? 0 : 1);
}

if (require.main === module) main();

module.exports = { parseArgs, parseEnvFile, check, formatReport };
