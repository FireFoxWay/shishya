#!/usr/bin/env node
'use strict';
/*
 * Tidefruit server: serves the game client over HTTP and runs the world over
 * WebSockets on the same port. No dependencies beyond Node itself.
 *
 *   node server.js            # http://localhost:3000
 *   PORT=8080 node server.js
 *   SAVE_FILE=/var/lib/tidefruit/saves.json node server.js
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const ws = require('./server/ws');
const { Game } = require('./server/game');
const { Store } = require('./server/store');

const PORT = +process.env.PORT || 3000;
const HOST = process.env.HOST || '0.0.0.0';
const ROOT = __dirname;
const SAVE_FILE = process.env.SAVE_FILE || path.join(ROOT, 'data', 'saves.json');
const TICK_HZ = 30;

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
};
// Only these two trees are served. Everything else (saves, server code) is not.
const MOUNTS = [['/shared/', path.join(ROOT, 'shared')], ['/', path.join(ROOT, 'public')]];

const store = new Store(SAVE_FILE);
const game = new Game(store);

const server = http.createServer((req, res) => {
  let url;
  try { url = decodeURIComponent((req.url || '/').split('?')[0]); } catch (_) { url = ''; }
  if (url === '/status') {
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    return res.end(JSON.stringify(game.status()));
  }
  for (const [prefix, dir] of MOUNTS) {
    if (!url.startsWith(prefix)) continue;
    let rel = url.slice(prefix.length) || 'index.html';
    const file = path.resolve(dir, rel);
    if (!file.startsWith(dir + path.sep)) break;
    return fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404, { 'Content-Type': 'text/plain' }); return res.end('Not found'); }
      res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
      res.end(data);
    });
  }
  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not found');
});

server.on('upgrade', (req, socket, head) => {
  if ((req.url || '').split('?')[0] !== '/ws') return socket.destroy();
  const conn = ws.accept(req, socket, head);
  if (conn) game.connect(conn);
});

let last = performance.now();
let acc = 0;
const STEP = 1000 / TICK_HZ;
// setInterval drifts; accumulate real time and run as many ticks as are due.
setInterval(() => {
  const now = performance.now();
  acc += now - last;
  last = now;
  let n = 0;
  while (acc >= STEP && n++ < 4) {
    acc -= STEP;
    try { game.tick(); } catch (e) { console.error('[tick]', e); }
  }
  if (acc > STEP * 4) acc = 0;
}, STEP / 2);

setInterval(() => { try { store.save(); } catch (e) { console.error('[store] save failed:', e.message); } }, 30000);

function shutdown() {
  console.log('\n[tidefruit] saving and shutting down…');
  try { store.save(); } catch (e) { console.error('[store] save failed:', e.message); }
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

server.listen(PORT, HOST, () => {
  console.log(`[tidefruit] sailing on http://localhost:${PORT}  (saves: ${SAVE_FILE})`);
});
