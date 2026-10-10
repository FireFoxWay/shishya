'use strict';
// Player saves, kept in memory and written to one JSON file. Writes go to a
// temporary file first and are renamed over the old one, so a crash mid-write
// leaves the previous save intact rather than half a file.
const fs = require('fs');
const path = require('path');

class Store {
  constructor(file) {
    this.file = file;
    this.map = new Map();
    this.dirty = false;
    try {
      const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
      for (const [k, v] of Object.entries(raw.players || {})) this.map.set(k, v);
      console.log(`[store] loaded ${this.map.size} saves from ${file}`);
    } catch (e) {
      if (e.code !== 'ENOENT') console.error('[store] could not read saves, starting empty:', e.message);
    }
  }

  get(key) { return this.map.get(key); }
  set(key, val) { this.map.set(key, val); this.dirty = true; }
  values() { return this.map.values(); }
  markDirty() { this.dirty = true; }

  // Online players mutate their save objects in place, so a periodic save
  // writes whatever is current whether or not anything flagged it.
  save() {
    const out = { savedAt: new Date().toISOString(), players: Object.fromEntries(this.map) };
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = this.file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(out));
    fs.renameSync(tmp, this.file);
    this.dirty = false;
  }
}

module.exports = { Store };
