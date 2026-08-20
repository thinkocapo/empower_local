import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { recordHeapSample } from '../utils/memoryMetrics';

// How long after a route commits to take the "settled" reading. Long enough for
// data fetches (products, cart) to resolve and render.
const SETTLE_DELAY_MS = 1200;

/**
 * Records a heap reading at each step of a route transition, so the journey
 * home -> products -> cart -> checkout -> complete produces a labelled series
 * rather than an undifferentiated line.
 *
 * Three samples per route:
 *   route_enter   - the new route has committed and painted
 *   route_settled - SETTLE_DELAY_MS later, after fetches have rendered
 *   route_leave   - just before the next route mounts
 *
 * Mount this inside the router, next to ScrollToTop.
 */
export default function MemoryMetrics() {
  const { pathname } = useLocation();

  useEffect(() => {
    recordHeapSample({ phase: 'route_enter', route: pathname });

    const settleTimer = setTimeout(() => {
      recordHeapSample({ phase: 'route_settled', route: pathname });
    }, SETTLE_DELAY_MS);

    return () => {
      clearTimeout(settleTimer);
      recordHeapSample({ phase: 'route_leave', route: pathname });
    };
  }, [pathname]);

  return null;
}
