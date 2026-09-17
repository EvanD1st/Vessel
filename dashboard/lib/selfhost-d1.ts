import { existsSync, lstatSync } from 'node:fs';
import { isAbsolute } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

// Only the optional Node build imports this module. Cloudflare keeps its D1 binding.
// A single connection gives D1's batch() the same atomicity used by account writes.
let database: DatabaseSync | undefined;

function sqlite(): DatabaseSync {
  if (database) return database;
  const location = process.env.VESSEL_SQLITE_PATH;
  if (!location || !isAbsolute(location) || !existsSync(location) || !lstatSync(location).isFile()) {
    throw new Error('VESSEL_SQLITE_PATH must name the provisioned private SQLite file.');
  }
  const opened = new DatabaseSync(location, { timeout: 5000, enableForeignKeyConstraints: true });
  opened.exec('PRAGMA journal_mode=WAL');
  database = opened;
  return opened;
}

type Params = Array<string | number | null | Uint8Array>;
class Prepared {
  constructor(readonly sql: string, readonly params: Params = []) {}
  bind(...params: Params): Prepared { return new Prepared(this.sql, params); }
  execute() {
    const stmt = sqlite().prepare(this.sql);
    if (stmt.columns().length) return { results: stmt.all(...this.params), success: true, meta: { changes: 0 } };
    const result = stmt.run(...this.params);
    return { results: [], success: true, meta: { changes: result.changes, last_row_id: Number(result.lastInsertRowid) } };
  }
  async run() { return this.execute(); }
  async all() { return this.execute(); }
  async first<T = Record<string, unknown>>(column?: string): Promise<T | null> {
    const row = sqlite().prepare(this.sql).get(...this.params) as Record<string, unknown> | undefined;
    return row ? (column ? row[column] as T : row as T) : null;
  }
  async raw(options?: { columnNames?: boolean }) {
    const stmt = sqlite().prepare(this.sql);
    const columns = stmt.columns().map(item => item.name);
    const rows = stmt.all(...this.params).map(row => columns.map(name => row[name]));
    return options?.columnNames ? [columns, ...rows] : rows;
  }
}

export const d1 = {
  prepare(sql: string) { return new Prepared(sql); },
  async batch(statements: Prepared[]) {
    const db = sqlite();
    db.exec('BEGIN IMMEDIATE');
    try {
      const results = statements.map(statement => statement.execute());
      db.exec('COMMIT');
      return results;
    } catch (error) { db.exec('ROLLBACK'); throw error; }
  },
  async exec(sql: string) { sqlite().exec(sql); return { count: 1, duration: 0 }; },
} as unknown as D1Database;
