const http = require('node:http');
const { Pool } = require('pg');
const { createClient } = require('redis');

const QUEUE_KEY = 'voting:jobs';
const PROCESSING_KEY = 'voting:processing';
const DEAD_LETTER_KEY = 'voting:dead-letter';

function log(level, message, details = {}) {
  process.stdout.write(`${JSON.stringify({ level, message, ...details, timestamp: new Date().toISOString() })}\n`);
}

async function processJob({ payload, pool, redis }) {
  let job;
  try {
    job = JSON.parse(payload);
  } catch {
    await redis.lPush(DEAD_LETTER_KEY, payload);
    await redis.lRem(PROCESSING_KEY, 1, payload);
    log('error', 'Rejected malformed voting job');
    return;
  }

  if (!Number.isInteger(job.user_id) || !Number.isInteger(job.election_id) || !Number.isInteger(job.candidate_id)) {
    await redis.lPush(DEAD_LETTER_KEY, payload);
    await redis.lRem(PROCESSING_KEY, 1, payload);
    log('error', 'Rejected voting job with invalid identifiers');
    return;
  }

  const connection = await pool.connect();
  try {
    await connection.query('BEGIN');
    await connection.query(
      'INSERT INTO votes (user_id, election_id, candidate_id) VALUES ($1, $2, $3) ON CONFLICT (user_id, election_id) DO NOTHING',
      [job.user_id, job.election_id, job.candidate_id],
    );
    await connection.query('COMMIT');
  } catch (error) {
    await connection.query('ROLLBACK').catch(() => {});
    throw error;
  } finally {
    connection.release();
  }

  await redis.del(`voting:results:${job.election_id}`);
  await redis.lRem(PROCESSING_KEY, 1, payload);
  log('info', 'Processed voting job', { user_id: job.user_id, election_id: job.election_id, candidate_id: job.candidate_id });
}

function startHealthServer({ redis, pool, port = 3001 }) {
  const server = http.createServer(async (request, response) => {
    if (request.url !== '/health') {
      response.writeHead(404, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ error: 'Resource not found.' }));
      return;
    }
    try {
      await Promise.all([redis.ping(), pool.query('SELECT 1')]);
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ status: 'ok' }));
    } catch (error) {
      log('error', 'Worker health check failed', { error: error.message });
      response.writeHead(503, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ status: 'unhealthy' }));
    }
  });
  server.listen(port, '0.0.0.0', () => log('info', 'Worker health endpoint listening', { port }));
  return server;
}

async function requeueProcessingJobs(redis) {
  while (await redis.rPopLPush(PROCESSING_KEY, QUEUE_KEY)) {
    log('warn', 'Recovered an in-flight voting job');
  }
}

async function startWorker() {
  const redis = createClient({ url: process.env.REDIS_URL || 'redis://localhost:6379/0' });
  redis.on('error', (error) => log('error', 'Redis client error', { error: error.message }));
  await redis.connect();
  const pool = new Pool({
    connectionString: process.env.WORKER_DATABASE_URL || process.env.DATABASE_URL || 'postgresql://voting:voting@localhost:5432/voting',
    max: 5,
  });
  await pool.query('SELECT 1');
  const port = Number.parseInt(process.env.WORKER_HEALTH_PORT || '3001', 10);
  startHealthServer({ redis, pool, port });

  await requeueProcessingJobs(redis);
  log('info', 'Voting worker started');
  while (true) {
    let payload;
    try {
      payload = await redis.blMove(QUEUE_KEY, PROCESSING_KEY, 'LEFT', 'RIGHT', 5);
      if (payload === null) continue;
      await processJob({ payload, pool, redis });
    } catch (error) {
      log('error', 'Voting job processing failed; it will be retried', { error: error.message });
      if (payload !== undefined && payload !== null) {
        await redis.lRem(PROCESSING_KEY, 1, payload).catch(() => {});
        await redis.lPush(QUEUE_KEY, payload).catch(() => {});
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
}

if (require.main === module) {
  startWorker().catch((error) => {
    log('error', 'Worker startup failed', { error: error.message });
    process.exitCode = 1;
  });
}

module.exports = { processJob, requeueProcessingJobs, startHealthServer };
