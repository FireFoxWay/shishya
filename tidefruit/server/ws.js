'use strict';
// A small RFC 6455 WebSocket server: enough for browsers talking JSON text
// frames to the game. No extensions, no compression, server frames unmasked.
const crypto = require('crypto');
const { EventEmitter } = require('events');

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const MAX_MESSAGE = 64 * 1024;
// A client that cannot keep up gets snapshots skipped above this much queued
// output, and is dropped above the hard limit.
const SOFT_BACKLOG = 512 * 1024;
const HARD_BACKLOG = 4 * 1024 * 1024;

class WSConn extends EventEmitter {
  constructor(socket, head, req) {
    super();
    this.socket = socket;
    this.req = req;
    this.buf = head && head.length ? Buffer.from(head) : Buffer.alloc(0);
    this.frags = null;
    this.open = true;
    socket.setNoDelay(true);
    socket.on('data', (d) => this._onData(d));
    socket.on('close', () => this._closed());
    socket.on('error', () => this._closed());
    if (this.buf.length) setImmediate(() => this._onData(Buffer.alloc(0)));
  }

  get congested() { return this.socket.writableLength > SOFT_BACKLOG; }

  send(str) {
    if (!this.open) return;
    if (this.socket.writableLength > HARD_BACKLOG) { this.close(1008, 'too slow'); return; }
    this._frame(0x1, Buffer.from(str, 'utf8'));
  }

  close(code = 1000, reason = '') {
    if (!this.open) return;
    const r = Buffer.from(reason);
    const p = Buffer.alloc(2 + r.length);
    p.writeUInt16BE(code, 0);
    r.copy(p, 2);
    try { this._frame(0x8, p); } catch (_) { /* socket already gone */ }
    this.open = false;
    this.socket.end();
    this._closed();
  }

  _frame(op, payload) {
    const len = payload.length;
    let header;
    if (len < 126) { header = Buffer.alloc(2); header[1] = len; }
    else if (len < 65536) { header = Buffer.alloc(4); header[1] = 126; header.writeUInt16BE(len, 2); }
    else { header = Buffer.alloc(10); header[1] = 127; header.writeBigUInt64BE(BigInt(len), 2); }
    header[0] = 0x80 | op;
    this.socket.write(Buffer.concat([header, payload]));
  }

  _onData(d) {
    if (d.length) this.buf = this.buf.length ? Buffer.concat([this.buf, d]) : d;
    while (this.open) {
      const b = this.buf;
      if (b.length < 2) return;
      const fin = (b[0] & 0x80) !== 0;
      const op = b[0] & 0x0f;
      const masked = (b[1] & 0x80) !== 0;
      let len = b[1] & 0x7f;
      let off = 2;
      if (len === 126) { if (b.length < 4) return; len = b.readUInt16BE(2); off = 4; }
      else if (len === 127) {
        if (b.length < 10) return;
        const big = b.readBigUInt64BE(2);
        if (big > BigInt(MAX_MESSAGE)) return this.close(1009, 'too big');
        len = Number(big); off = 10;
      }
      if (len > MAX_MESSAGE) return this.close(1009, 'too big');
      // Clients must mask; a frame that does not is a protocol error.
      if (!masked) return this.close(1002, 'unmasked');
      if (b.length < off + 4 + len) return;
      const mask = b.subarray(off, off + 4);
      const payload = Buffer.from(b.subarray(off + 4, off + 4 + len));
      for (let i = 0; i < len; i++) payload[i] ^= mask[i & 3];
      this.buf = b.subarray(off + 4 + len);
      this._onFrame(fin, op, payload);
    }
  }

  _onFrame(fin, op, payload) {
    if (op === 0x8) { this.close(1000); return; }
    if (op === 0x9) { this._frame(0xA, payload); return; }
    if (op === 0xA) return;
    if (op === 0x0) {
      if (!this.frags) return this.close(1002, 'stray continuation');
      this.frags.push(payload);
      if (this.frags.reduce((n, p) => n + p.length, 0) > MAX_MESSAGE) return this.close(1009, 'too big');
      if (fin) { const all = Buffer.concat(this.frags); this.frags = null; this.emit('message', all.toString('utf8')); }
      return;
    }
    if (op === 0x1 || op === 0x2) {
      if (!fin) { this.frags = [payload]; return; }
      this.emit('message', payload.toString('utf8'));
    }
  }

  _closed() {
    if (this._done) return;
    this._done = true;
    this.open = false;
    this.emit('close');
  }
}

// Completes the handshake on an HTTP 'upgrade' and hands back a connection.
function accept(req, socket, head) {
  const key = req.headers['sec-websocket-key'];
  if (!key || String(req.headers.upgrade || '').toLowerCase() !== 'websocket') {
    socket.end('HTTP/1.1 400 Bad Request\r\n\r\n');
    return null;
  }
  const acceptKey = crypto.createHash('sha1').update(key + GUID).digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n' +
    'Sec-WebSocket-Accept: ' + acceptKey + '\r\n\r\n');
  return new WSConn(socket, head, req);
}

module.exports = { accept };
