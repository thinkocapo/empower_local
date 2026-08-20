import * as Sentry from '@sentry/react';

/**
 * Browser JS heap instrumentation.
 *
 * Sentry has no built-in memory/heap collection for the browser -- browser
 * profiling is CPU-only, and there is no heap profiler in any JS SDK. So we
 * read the heap ourselves and ship it two ways:
 *
 *   1. As an Application Metric gauge (`Sentry.metrics.gauge`). Metrics are NOT
 *      subject to trace sampling, so the curve stays unbroken even at a low
 *      tracesSampleRate. This is the artifact you chart over time.
 *   2. As attributes on whatever span is active. That makes a heap reading
 *      correlatable to the exact trace it happened in, so you can jump from
 *      "memory climbed here" to "this is the request that was running".
 *
 * Every metric the SDK emits already carries trace_id and span_id, so the two
 * views join up on their own.
 *
 * CAVEAT: performance.memory is Chromium-only (Chrome/Edge). Firefox and Safari
 * return nothing and this module no-ops. The cross-browser alternative,
 * performance.measureUserAgentSpecificMemory(), requires COOP+COEP
 * cross-origin isolation, which this app does not set.
 */

const HEAP_USED_METRIC = 'browser.memory.heap_used';
const HEAP_UTILIZATION_METRIC = 'browser.memory.heap_utilization';

const DEFAULT_SAMPLE_INTERVAL_MS = 5000;
const MIN_SAMPLE_INTERVAL_MS = 250;

const sessionStartedAt = Date.now();

let intervalId = null;
let pagehideHandler = null;
let unsupportedAlreadyLogged = false;

/**
 * Read the current JS heap. Returns null where the API is unavailable.
 */
function readHeap() {
  const memory =
    typeof performance !== 'undefined' ? performance.memory : undefined;

  if (!memory || typeof memory.usedJSHeapSize !== 'number') {
    return null;
  }

  return {
    usedBytes: memory.usedJSHeapSize,
    totalBytes: memory.totalJSHeapSize,
    limitBytes: memory.jsHeapSizeLimit,
  };
}

/**
 * How long this browsing session has been alive. This is the axis that matters
 * for the "editor gets slow after two hours" story -- heap plotted against
 * time-in-session rather than wall clock.
 */
function sessionElapsedMs() {
  return Date.now() - sessionStartedAt;
}

function currentRoute() {
  return typeof window !== 'undefined' && window.location
    ? window.location.pathname
    : 'unknown';
}

/**
 * Capture one heap reading.
 *
 * @param {object}  options
 * @param {string}  options.phase - Why this sample was taken. One of:
 *   app_load, interval, route_enter, route_settled, route_leave, pagehide.
 * @param {string} [options.route] - Route the sample belongs to. Defaults to
 *   the current pathname.
 */
export function recordHeapSample({ phase, route } = {}) {
  const heap = readHeap();

  if (!heap) {
    if (!unsupportedAlreadyLogged) {
      unsupportedAlreadyLogged = true;
      console.warn(
        '[memoryMetrics] performance.memory unavailable (non-Chromium browser); heap metrics disabled'
      );
    }
    return null;
  }

  const resolvedRoute = route || currentRoute();
  const elapsedMs = sessionElapsedMs();

  const attributes = {
    phase: phase || 'unknown',
    route: resolvedRoute,
    session_elapsed_ms: elapsedMs,
    session_elapsed_min: Number((elapsedMs / 60000).toFixed(2)),
    heap_total_bytes: heap.totalBytes,
    heap_limit_bytes: heap.limitBytes,
  };

  // The gauge -- sampling-independent, this is the time series to chart.
  Sentry.metrics.gauge(HEAP_USED_METRIC, heap.usedBytes, {
    unit: 'byte',
    attributes,
  });

  // Percent of the browser's heap ceiling in use. Easier to alert on than raw
  // bytes, because the ceiling differs by device.
  if (heap.limitBytes > 0) {
    Sentry.metrics.gauge(
      HEAP_UTILIZATION_METRIC,
      Number(((heap.usedBytes / heap.limitBytes) * 100).toFixed(2)),
      { unit: 'percent', attributes }
    );
  }

  // Correlate the reading to the active trace, when there is one.
  const activeSpan = Sentry.getActiveSpan();
  if (activeSpan) {
    activeSpan.setAttributes({
      'memory.heap_used_bytes': heap.usedBytes,
      'memory.heap_used_mb': Number(
        (heap.usedBytes / 1024 / 1024).toFixed(2)
      ),
      'memory.heap_limit_bytes': heap.limitBytes,
      'memory.sample_phase': attributes.phase,
      'memory.session_elapsed_ms': elapsedMs,
    });
  }

  return heap;
}

/**
 * Sample interval, overridable via ?heapInterval=1000 so a live demo does not
 * have to wait 5s between points.
 */
function resolveSampleInterval() {
  try {
    const requested = new URLSearchParams(window.location.search).get(
      'heapInterval'
    );
    if (!requested) return DEFAULT_SAMPLE_INTERVAL_MS;

    const parsed = Number.parseInt(requested, 10);
    if (Number.isNaN(parsed)) return DEFAULT_SAMPLE_INTERVAL_MS;

    return Math.max(parsed, MIN_SAMPLE_INTERVAL_MS);
  } catch {
    return DEFAULT_SAMPLE_INTERVAL_MS;
  }
}

/**
 * Take a baseline reading at app load, then sample on a timer for the life of
 * the session. Safe to call more than once; extra calls are ignored.
 */
export function startHeapSampling() {
  if (intervalId !== null) {
    return;
  }

  if (!readHeap()) {
    recordHeapSample({ phase: 'app_load' }); // logs the unsupported warning once
    return;
  }

  const intervalMs = resolveSampleInterval();

  // Baseline: SDK initialized, app booting.
  recordHeapSample({ phase: 'app_load' });

  intervalId = setInterval(() => {
    recordHeapSample({ phase: 'interval' });
  }, intervalMs);

  // A final reading as the tab goes away, so the curve has an endpoint.
  pagehideHandler = () => recordHeapSample({ phase: 'pagehide' });
  window.addEventListener('pagehide', pagehideHandler);

  console.log(
    `[memoryMetrics] heap sampling every ${intervalMs}ms -> ${HEAP_USED_METRIC}`
  );
}

/**
 * Stop sampling and detach listeners.
 */
export function stopHeapSampling() {
  if (intervalId !== null) {
    clearInterval(intervalId);
    intervalId = null;
  }

  if (pagehideHandler) {
    window.removeEventListener('pagehide', pagehideHandler);
    pagehideHandler = null;
  }
}
