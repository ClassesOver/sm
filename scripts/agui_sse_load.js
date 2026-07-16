#!/usr/bin/env node
const runtimeUrl = process.argv[2]
const concurrency = Number(process.argv[3] || 200)
const timeoutMs = Number(process.env.AGUI_LOAD_TIMEOUT_MS || 180000)
const cookie = process.env.AGUI_COOKIE || ''

if (!runtimeUrl || !/^https?:\/\//.test(runtimeUrl)) {
  console.error('Usage: node scripts/agui_sse_load.js <absolute-runtime-url> [concurrency]')
  process.exit(2)
}

async function run(index) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  const started = Date.now()
  let events = 0
  try {
    const response = await fetch(runtimeUrl, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        'X-Request-ID': `load-${index}-${Date.now()}`,
        ...(cookie ? { Cookie: cookie } : {})
      },
      body: JSON.stringify({
        threadId: `load-thread-${index}`,
        runId: `load-run-${index}-${Date.now()}`,
        messages: [{ id: `message-${index}`, role: 'user', content: 'health check' }],
        tools: [], context: [], state: {}, resume: []
      }),
      signal: controller.signal
    })
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const chunk = await reader.read()
      if (chunk.done) break
      buffer += decoder.decode(chunk.value, { stream: true })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      events += blocks.length
    }
    return { ok: true, events, durationMs: Date.now() - started }
  } catch (error) {
    return { ok: false, error: error.message, durationMs: Date.now() - started }
  } finally {
    clearTimeout(timeout)
  }
}

Promise.all(Array.from({ length: concurrency }, (_, index) => run(index))).then((results) => {
  const failures = results.filter((item) => !item.ok)
  const durations = results.map((item) => item.durationMs).sort((a, b) => a - b)
  const summary = {
    concurrency,
    succeeded: results.length - failures.length,
    failed: failures.length,
    errorRate: failures.length / results.length,
    p95DurationMs: durations[Math.min(durations.length - 1, Math.floor(durations.length * 0.95))],
    sampleErrors: failures.slice(0, 5)
  }
  console.log(JSON.stringify(summary, null, 2))
  process.exit(summary.errorRate < 0.01 ? 0 : 1)
})
