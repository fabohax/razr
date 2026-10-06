"""Atomic processing state and one event per strategy/candle/direction."""
import hashlib
import json
import sqlite3
import time

STRATEGY_VERSION = 'macd-ema-first-zero-filter-v2'


def namespace(cfg):
    identity = [cfg.exchange, 'spot', cfg.symbol, cfg.timeframe, STRATEGY_VERSION,
                cfg.macd_fast, cfg.macd_slow, cfg.macd_signal]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


class State:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS processing (
                namespace TEXT PRIMARY KEY, watermark INTEGER NOT NULL,
                fast REAL NOT NULL, slow REAL NOT NULL, signal REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, namespace TEXT NOT NULL, candle INTEGER NOT NULL,
                direction TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(namespace, candle, direction));
            CREATE TABLE IF NOT EXISTS deliveries (
                event_id TEXT NOT NULL REFERENCES events(id), channel TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY(event_id, channel));
        ''')

        # Additive migration preserves Phase 2 events, watermarks and jobs.
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(deliveries)')}
        for name, definition in (
            ('retry_count', 'INTEGER NOT NULL DEFAULT 0'),
            ('next_retry_at', 'REAL NOT NULL DEFAULT 0'),
            ('last_error', 'TEXT'), ('updated_at', 'REAL')):
            if name not in columns:
                self.db.execute(f'ALTER TABLE deliveries ADD COLUMN {name} {definition}')
        self.db.commit()

    def checkpoint(self, ns):
        return self.db.execute('SELECT watermark, fast, slow, signal FROM processing WHERE namespace=?', (ns,)).fetchone()

    def commit(self, ns, checkpoint, events, channels):
        with self.db:
            # Guard against another process advancing this namespace during calculation.
            current = self.checkpoint(ns)
            if current and current[0] >= checkpoint[0]:
                return
            for event in events:
                cursor = self.db.execute('INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?)',
                    (event['event_id'], ns, event['candle_ms'], event['signal'], json.dumps(event)))
                if cursor.rowcount and event['deliverable']:
                    self.db.executemany('INSERT INTO deliveries(event_id, channel) VALUES (?, ?)',
                                        [(event['event_id'], channel) for channel in channels])
            self.db.execute('INSERT OR REPLACE INTO processing VALUES (?, ?, ?, ?, ?)', (ns, *checkpoint))

    def pending(self, due_at=None):
        query = "SELECT e.payload, d.channel FROM deliveries d JOIN events e ON e.id=d.event_id WHERE d.status='pending'"
        params = ()
        if due_at is not None:
            query += ' AND d.next_retry_at<=?'
            params = (due_at,)
        return self.db.execute(query + ' ORDER BY e.candle, d.channel', params).fetchall()

    def delivered(self, event_id, channel, status='delivered'):
        with self.db:
            self.db.execute("UPDATE deliveries SET status=?, next_retry_at=0, updated_at=? WHERE event_id=? AND channel=?", (status, time.time(), event_id, channel))

    def retry_count(self, event_id, channel):
        return self.db.execute('SELECT retry_count FROM deliveries WHERE event_id=? AND channel=?',
                               (event_id, channel)).fetchone()[0]

    def failed_attempt(self, event_id, channel, error, now, delay, max_attempts, permanent=False):
        with self.db:
            count = self.retry_count(event_id, channel) + 1
            status = 'failed' if permanent or count >= max_attempts else 'pending'
            self.db.execute('UPDATE deliveries SET retry_count=?, next_retry_at=?, last_error=?, updated_at=?, status=? WHERE event_id=? AND channel=?',
                            (count, now + delay, error, now, status, event_id, channel))

    def requeue_failed(self):
        with self.db:
            cursor = self.db.execute("UPDATE deliveries SET status='pending', retry_count=0, next_retry_at=0 WHERE status='failed'")
            return cursor.rowcount

    def health(self):
        counts = dict(self.db.execute('SELECT status, count(*) FROM deliveries GROUP BY status'))
        due = self.db.execute("SELECT min(next_retry_at) FROM deliveries WHERE status='pending'").fetchone()[0]
        return counts, due

    def close(self):
        self.db.close()
