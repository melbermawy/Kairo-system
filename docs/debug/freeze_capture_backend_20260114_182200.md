# Backend Freeze Capture - 2026-01-14 18:22:00 UTC

## Capture Window

- **Start**: 2026-01-14 18:17:45 UTC
- **End**: 2026-01-14 18:22:47 UTC
- **Duration**: ~5 minutes (real frontend session)
- **Server config**: `KAIRO_LOG_DB_TIMING=1`

---

## Summary

| Metric | Value |
|--------|-------|
| Total API requests | 14 |
| Storm warnings | **0** |
| HTTP 500 errors | **0** |
| Max latency | 2600.7 ms (compile kickoff) |
| Avg latency | 1170 ms |
| Min latency | 728.5 ms |

**Conclusion**: No storms. No errors. Backend healthy. Latency is network-bound (~700-800ms baseline to Supabase).

---

## 1. Storm Warnings

**Count: 0**

No request storms detected. The frontend is making reasonable polling intervals (~5-10s between status checks).

---

## 2. HTTP 500 Errors

**Count: 0**

All requests succeeded.

---

## 3. Request Counts by Path

| Path (normalized) | Count | Notes |
|-------------------|-------|-------|
| `GET /api/brands/:id/brandbrain/compile/:id/status` | 8 | Polling for compile completion |
| `POST /api/brands/:id/brandbrain/compile` | 3 | Compile kickoffs |
| `POST /api/brands/:id/sources` | 1 | Source creation |
| `GET /api/brands/:id/brandbrain/latest` | 1 | Fetch latest snapshot |
| `GET /api/brands/:id/bootstrap` | 1 | Page init |

**Polling behavior**: Status checks every ~5-10 seconds. Not excessive.

---

## 4. Slowest Endpoints

| Rank | Endpoint | Latency | Bytes | Notes |
|------|----------|---------|-------|-------|
| 1 | `POST /brandbrain/compile` | 2600.7 ms | 206 | Compile kickoff (async) |
| 2 | `POST /brandbrain/compile` | 2258.7 ms | 1156 | Short-circuit return |
| 3 | `POST /brandbrain/compile` | 2168.6 ms | 206 | Compile kickoff |
| 4 | `GET /bootstrap` | 1173.7 ms | 1531 | Page init (5 queries) |
| 5 | `POST /sources` | 1172.9 ms | 313 | Create source |

**Analysis**: Compile kickoff is slowest (2-2.6s) due to multiple DB operations. This is expected for the work-path endpoint.

---

## 5. Payload Sizes

| Endpoint | Size | Notes |
|----------|------|-------|
| `POST /brandbrain/compile` (202) | 206 bytes | Async kickoff response |
| `POST /brandbrain/compile` (200) | 1,156 bytes | Short-circuit with snapshot |
| `GET /compile/:id/status` (RUNNING) | 159 bytes | Polling response |
| `GET /compile/:id/status` (SUCCEEDED) | 1,662 bytes | With snapshot |
| `GET /bootstrap` | 1,531 bytes | Full init payload |
| `GET /brandbrain/latest` | 1,119 bytes | Snapshot (885 bytes) |

**Conclusion**: All payloads are small (<2KB).

---

## 6. Compile Polling Timeline

```
18:20:40 POST /compile → 202 (kickoff, 2600ms)
18:20:57 POST /compile → 202 (kickoff, 2168ms)
18:20:59 GET /status → 200 (RUNNING, 785ms)
18:21:03 GET /status → 200 (RUNNING, 798ms)
18:21:09 GET /status → 200 (RUNNING, 728ms)
18:21:16 GET /status → 200 (RUNNING, 776ms)
18:21:27 GET /status → 200 (RUNNING, 786ms)
18:21:38 GET /status → 200 (SUCCEEDED, 1000ms, 1662 bytes)
18:21:49 GET /status → 200 (SUCCEEDED, 852ms)
18:22:00 GET /status → 200 (SUCCEEDED, 1005ms)
18:22:44 POST /compile → 200 (short-circuit, 2258ms)
```

**Observations**:
- Compile took ~38 seconds to complete (18:21:00 → 18:21:38)
- Frontend polled every ~5-10 seconds (reasonable)
- No excessive polling detected

---

## 7. Raw Timing Logs

```
INFO timing POST /api/brands/:id/sources | status=201 | ms=1172.9 | bytes=313
INFO timing POST /api/brands/:id/brandbrain/compile | status=202 | ms=2600.7 | bytes=206
INFO timing POST /api/brands/:id/brandbrain/compile | status=202 | ms=2168.6 | bytes=206
INFO timing GET /api/brands/:id/brandbrain/compile/:id/status | status=200 | ms=785.0 | bytes=159
INFO timing GET /api/brands/:id/brandbrain/compile/:id/status | status=200 | ms=798.4 | bytes=159
INFO timing GET /api/brands/:id/brandbrain/compile/:id/status | status=200 | ms=728.5 | bytes=159
INFO timing GET /api/brands/:id/brandbrain/compile/:id/status | status=200 | ms=776.3 | bytes=159
INFO timing GET /api/brands/:id/brandbrain/compile/:id/status | status=200 | ms=786.5 | bytes=159
INFO timing GET /api/brands/:id/brandbrain/compile/:id/status | status=200 | ms=1000.5 | bytes=1662 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/compile/:id/status | status=200 | ms=852.7 | bytes=1662 | snapshot_bytes=885
INFO timing GET /api/brands/:id/brandbrain/compile/:id/status | status=200 | ms=1005.3 | bytes=1662 | snapshot_bytes=885
INFO timing POST /api/brands/:id/brandbrain/compile | status=200 | ms=2258.7 | bytes=1156
INFO timing GET /api/brands/:id/bootstrap | status=200 | ms=1173.7 | bytes=1531
INFO timing GET /api/brands/:id/brandbrain/latest | status=200 | ms=1071.1 | bytes=1119 | snapshot_bytes=885
```

---

## 8. Conclusions

1. **Backend is healthy**: No errors, no storms, all requests succeed.

2. **No request storms**: Frontend polls at reasonable intervals (~5-10s).

3. **Latency is network-bound**: ~700-800ms baseline to Supabase us-west-2.

4. **Payloads are small**: Max 1.6KB, not a bottleneck.

5. **Compile is the slowest operation**: 2-2.6s for kickoff, but this is expected.

6. **Frontend freeze is NOT caused by backend**. Investigate:
   - JavaScript main thread blocking during compile wait
   - React state updates causing re-render loops
   - Memory issues with snapshot data
   - useEffect dependencies
