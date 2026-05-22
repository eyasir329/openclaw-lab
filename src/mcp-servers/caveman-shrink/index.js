#!/usr/bin/env node
// caveman-shrink — MCP middleware that proxies an upstream MCP server and
// compresses prose fields so the model sees fewer tokens.
//
// Usage:
//   caveman-shrink <upstream-command> [...args]
//
// Example:
//   "mcpServers": {
//     "fs-shrunk": {
//       "command": "npx",
//       "args": ["caveman-shrink", "npx", "@modelcontextprotocol/server-filesystem", "/some/path"]
//     }
//   }

const { spawn } = require('child_process');
const { compressDescriptionsInPlace, compress } = require('./compress');

const args = process.argv.slice(2);
if (args.length === 0) {
  process.stderr.write('caveman-shrink: missing upstream command.\n');
  process.stderr.write('Usage: caveman-shrink <upstream-command> [...args]\n');
  process.exit(2);
}

const debug = process.env.CAVEMAN_SHRINK_DEBUG === '1';
const fields = (process.env.CAVEMAN_SHRINK_FIELDS || 'description')
  .split(',').map(s => s.trim()).filter(Boolean);

const upstream = spawn(args[0], args.slice(1), {
  stdio: ['pipe', 'pipe', 'inherit'],
});

upstream.on('error', err => {
  process.stderr.write(`caveman-shrink: failed to spawn upstream: ${err.message}\n`);
  process.exit(1);
});

upstream.on('exit', (code, signal) => {
  if (signal) process.exit(128 + (signal === 'SIGTERM' ? 15 : 9));
  process.exit(code || 0);
});

function makeLineBuffer(onLine) {
  let buf = '';
  return chunk => {
    buf += chunk.toString('utf8');
    let nl;
    while ((nl = buf.indexOf('\n')) !== -1) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      if (line.trim()) onLine(line);
    }
  };
}

function transformResponse(msg) {
  if (!msg || !msg.result || typeof msg.result !== 'object') return msg;
  const r = msg.result;
  let compressedSomething = false;

  for (const arrayName of ['tools', 'prompts', 'resources', 'resourceTemplates']) {
    if (Array.isArray(r[arrayName])) {
      for (const item of r[arrayName]) {
        for (const field of fields) {
          if (typeof item[field] === 'string') {
            const before = item[field];
            const out = compress(before).compressed;
            if (out !== before) {
              item[field] = out;
              compressedSomething = true;
              if (debug) {
                process.stderr.write(
                  `[caveman-shrink] ${arrayName}.${item.name || '?'}.${field}: ` +
                  `${before.length}→${out.length} bytes\n`
                );
              }
            }
          }
        }
      }
    }
  }

  if (!compressedSomething) compressDescriptionsInPlace(r, fields);

  return msg;
}

upstream.stdout.on('data', makeLineBuffer(line => {
  let msg;
  try { msg = JSON.parse(line); } catch {
    process.stdout.write(line + '\n');
    return;
  }
  const out = transformResponse(msg);
  process.stdout.write(JSON.stringify(out) + '\n');
}));

process.stdin.on('data', chunk => upstream.stdin.write(chunk));
process.stdin.on('end',  () => upstream.stdin.end());
