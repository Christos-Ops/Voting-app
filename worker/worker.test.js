const test = require('node:test');
const assert = require('node:assert/strict');

const { processJob, requeueProcessingJobs, startHealthServer } = require('./worker');

function createFakes() {
  const state = { queries: [], deleted: [], removed: [], dead: [], queue: [], processing: [] };
  const connection = {
    async query(sql, values) {
      state.queries.push({ sql, values });
    },
    release() {
      state.released = true;
    },
  };
  const pool = {
    async connect() {
      return connection;
    },
  };
  const redis = {
    async del(key) {
      state.deleted.push(key);
    },
    async lRem(key, _count, payload) {
      state.removed.push({ key, payload });
    },
    async lPush(key, payload) {
      (key === 'voting:dead-letter' ? state.dead : state.queue).push(payload);
    },
    async rPopLPush(from, to) {
      const source = from === 'voting:processing' ? state.processing : state.queue;
      const payload = source.pop();
      if (payload) (to === 'voting:jobs' ? state.queue : state.processing).unshift(payload);
      return payload || null;
    },
  };
  return { state, pool, redis };
}

test('persists an election vote transactionally and clears that election result cache', async () => {
  const fakes = createFakes();
  const payload = JSON.stringify({ user_id: 7, election_id: 12, candidate_id: 3 });
  await processJob({ payload, pool: fakes.pool, redis: fakes.redis });
  assert.deepEqual(fakes.state.queries.map((entry) => entry.sql), [
    'BEGIN',
    'INSERT INTO votes (user_id, election_id, candidate_id) VALUES ($1, $2, $3) ON CONFLICT (user_id, election_id) DO NOTHING',
    'COMMIT',
  ]);
  assert.deepEqual(fakes.state.queries[1].values, [7, 12, 3]);
  assert.deepEqual(fakes.state.deleted, ['voting:results:12']);
  assert.equal(fakes.state.released, true);
});

test('sends malformed jobs to dead letter queue', async () => {
  const fakes = createFakes();
  await processJob({ payload: '{broken', pool: fakes.pool, redis: fakes.redis });
  assert.deepEqual(fakes.state.dead, ['{broken']);
  assert.equal(fakes.state.queries.length, 0);
});

test('requeues jobs left in processing after restart', async () => {
  const fakes = createFakes();
  fakes.state.processing.push('one', 'two');
  await requeueProcessingJobs(fakes.redis);
  assert.deepEqual(fakes.state.queue, ['one', 'two']);
  assert.deepEqual(fakes.state.processing, []);
});

test('worker health reports dependency failures', async () => {
  let redisHealthy = true;
  const server = startHealthServer({
    port: 0,
    redis: {
      async ping() {
        if (!redisHealthy) throw new Error('Redis unavailable');
      },
    },
    pool: { async query() {} },
  });
  await new Promise((resolve) => server.once('listening', resolve));
  const url = `http://127.0.0.1:${server.address().port}/health`;
  try {
    assert.equal((await fetch(url)).status, 200);
    redisHealthy = false;
    assert.equal((await fetch(url)).status, 503);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
