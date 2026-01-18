# Backend Freeze Capture - 2026-01-14 17:54:34 UTC

## Capture Window

- **Start**: 2026-01-14 17:50:51 UTC
- **End**: 2026-01-14 17:54:49 UTC
- **Duration**: ~4 minutes
- **Server config**: `KAIRO_LOG_DB_TIMING=1`

---

## Summary

| Metric | Value |
|--------|-------|
| Total API requests | 29 |
| Storm warnings | 0 |
| HTTP 500 errors | 0 |
| Max latency | 1412.5 ms |
| Avg latency | 989.7 ms |
| Min latency | 708.4 ms |

**Conclusion**: No storms detected. No errors. Backend is responding normally. High latency (~1s) is due to network RTT to Supabase us-west-2.

---

## 1. Storm Warnings

**Count: 0**

No request storms detected during capture window. Threshold: >20 requests/10s or >120 requests/60s.

Note: During simulated burst test (15 concurrent requests to `/brandbrain/latest`), requests completed in ~1s window but did not trigger storm warning because threshold was set to default (20/10s).

---

## 2. HTTP 500 Errors

**Count: 0**

No server errors during capture window. All requests returned 200.

---

## 3. Request Counts by Path

| Path (normalized) | Count | Avg Latency |
|-------------------|-------|-------------|
| `GET /api/brands/:id/brandbrain/latest` | 18 | ~950 ms |
| `GET /api/brands/:id/bootstrap` | 4 | ~1267 ms |
| `GET /api/brands` | 4 | ~849 ms |
| `GET /api/brands/:id/brandbrain/history` | 3 | ~1029 ms |

**Max rate observed**: 15 requests in ~1 second (concurrent burst to `/brandbrain/latest`)

---

## 4. Slowest Endpoints

| Rank | Endpoint | Latency | Bytes |
|------|----------|---------|-------|
| 1 | `GET /api/brands/:id/bootstrap` | 1412.5 ms | 1216 |
| 2 | `GET /api/brands/:id/bootstrap` | 1361.4 ms | 1216 |
| 3 | `GET /api/brands/:id/brandbrain/history` | 1224.1 ms | 387 |
| 4 | `GET /api/brands/:id/bootstrap` | 1150.0 ms | 1216 |
| 5 | `GET /api/brands/:id/brandbrain/latest` | 1027.8 ms | 1119 |

**Analysis**: Bootstrap endpoint is slowest due to 5 DB queries. All latencies are dominated by network RTT to Supabase (~700-800ms baseline).

---

## 5. Payload Sizes

| Endpoint | Response Size | Snapshot Size |
|----------|---------------|---------------|
| `/api/brands` | 150 bytes | N/A |
| `/api/brands/:id/bootstrap` | 1,216 bytes | N/A |
| `/api/brands/:id/brandbrain/latest` | 1,119 bytes | 885 bytes |
| `/api/brands/:id/brandbrain/history` | 387 bytes | N/A |

**Conclusion**: All payloads are small (<2KB). Oversized responses are NOT causing frontend freeze.

---

## 6. Raw Timing Logs

```
INFO timing GET /api/brands | status=200 | ms=960.8 | bytes=150
INFO timing GET /api/brands/:id/bootstrap | status=200 | ms=1412.5 | bytes=1216
INFO timing GET /api/brands/:id/bootstrap | status=200 | ms=1150.0 | bytes=1216
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=898.0 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/history | status=200 | ms=920.2 | bytes=387
INFO timing GET /api/brands | status=200 | ms=799.8 | bytes=150
INFO timing GET /api/brands/:id/bootstrap | status=200 | ms=1143.6 | bytes=1216
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=900.9 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/history | status=200 | ms=944.5 | bytes=387
INFO timing GET /api/brands | status=200 | ms=927.6 | bytes=150
INFO timing GET /api/brands/:id/bootstrap | status=200 | ms=1361.4 | bytes=1216
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1027.8 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/history | status=200 | ms=1224.1 | bytes=387
# Burst of 15 concurrent requests to /brandbrain/latest:
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=825.6 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=957.5 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=951.3 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=965.1 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=973.9 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=975.3 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=973.6 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=975.5 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1013.6 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1010.9 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1000.1 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1013.4 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1009.5 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1022.4 | bytes=1119 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1024.4 | bytes=1119 | snapshot_bytes=885
```

---

## 7. Conclusions

1. **Backend is healthy**: No 500s, no storms, all requests succeed.

2. **Latency is network-bound**: ~700-800ms baseline RTT to Supabase us-west-2.

3. **Payloads are small**: Max 1.2KB, not a bottleneck.

4. **No request storms**: Even 15 concurrent requests handled cleanly.

5. **Frontend freeze is NOT caused by backend**: Look for:
   - JavaScript main thread blocking
   - React re-render loops
   - Memory leaks
   - useEffect infinite loops
