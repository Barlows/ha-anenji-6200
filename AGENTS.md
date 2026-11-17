# AGENTS.md

Handoff for AI assistants (Claude or any other) picking up work on this repository
in a new chat. **Read this whole file first**, then ask Sean what he wants. It records
the owner, the current state of his live system, what has been tried, how releases
and tests work here, and how to check on the running integration. Last updated
**2026-11-17**, at release **1.0.4**. If the date is much later, re-verify the
"Current status" section against the live system before relying on it.

## 1. What this is

- **Repo:** `Barlows/ha-anenji-6200`, Sean's fork of `groove-max/ha-eybond-local`
  (upstream's integration for hybrid solar inverters behind EyeBond Wi-Fi collectors).
- **Purpose:** Sean's own HACS-installed build, shown in HACS as **"EyeBond Local SC"**,
  for **one** inverter: an Anenji / Aninerel **SMG 6200** (firmware 7904), reached
  through an EyeBond collector (dongle) on his LAN at **192.168.0.201** (it was
  .202 at one point). Domain `eybond_local`, driver `modbus_smg`, effective profile
  `modbus_smg/models/anenji_op2_6200.json` (HA shows the model as "Aninerel 6200
  (dual output)"). Polling is Modbus over the EyeBond envelope on the local network;
  nothing depends on the vendor cloud.
- **Owner:** Sean (GitHub `Barlows`), London (Home Assistant timezone
  `Europe/London`; he sometimes travels, so his message timestamps can be in another
  zone, while HA logs are UTC/London).
- **Why a fork:** truncated and misframed collector replies were costing refreshes and
  reconnects. The fork carries fixes upstream does not have, plus proper numbered
  releases so Sean can roll back (see sections 3 and 5).
- **Versions are the fork's own.** 1.0.0 and later are the fork's number space.
  Upstream is on `0.3.0-beta.5` / a frozen `0.3.0-rc.1`; the two numberings are
  unrelated. The fork's merge base with upstream is late September 2026, and
  `UPSTREAM_CHANGELOG.md` keeps upstream's history.
- **Other inverter code stays.** Sean asked whether to strip the code for the other
  inverter families and decided **no, leave it**. Do not propose removing it again.

## 2. Working with Sean

- He mostly asks short status questions: "Any change?", "What about now?", "Still
  ok?", "Anything new in the groove repo?". **"What about now?" means check the
  health of the live system and recheck upstream, then summarise.** He says
  "Installed" or "Updated" once he has updated in HACS; then check the logs.
- Keep replies short: what changed or did not, the numbers, a clear recommendation.
  He says "do it" when he wants a proposed change built. Do not start unrequested work
  (for example upstream cherry-picks) without his go-ahead.
- To install a release he uses HACS: update, then restart Home Assistant. To roll
  back: HACS, EyeBond Local SC, menu, **Redownload**, pick the version, restart.
- Tell him when something is merged and released, and how to update; do not make him
  ask. Say plainly when a fix is unproven on his unit.

## 3. Release history (fork)

| Version | Date | What |
|---|---|---|
| 1.0.0 | 2026-10-09 | First numbered release. Release workflow. The collector's unwrapped ("bare") Modbus RTU replies that arrive outside the EyeBond envelope are skipped when CRC-verified instead of resetting the session. |
| 1.0.1 | 2026-10-20 | A truncated reply whose missing tail arrives glued in front of the next reply ("shape A") is recovered. Raw bytes of rejected answers are logged. |
| 1.0.2 | 2026-10-20 | A truncated reply whose tail arrives alone as the retry's whole answer ("shape B") is reassembled (prefix plus tail, CRC-verified). |
| 1.0.3 | 2026-10-21 | A cut-off bare 113/93-byte reply is skipped instead of closing the session. A complete reply of the wrong byte count (previous read arriving a slot late) is retried. |
| 1.0.4 | 2026-11-03 | Third read attempt when cut-short answers are held. A leftover fragment where a frame header should be is dropped and the stream resynchronised (on a session that already delivered a valid frame; at most 2 in a row). |

Full notes: [CHANGELOG.md](CHANGELOG.md). `1.0.4` is installed on Sean's Home
Assistant (HACS shows installed = available = v1.0.4).

## 4. The fault and the code that handles it

The EyeBond collector sits between Home Assistant and the inverter. Frames use an
8-byte header (TID, devcode, length, devaddr, fcode). Observed misbehaviour, all on
the collector/dongle side:

- **Truncated replies.** For a read of N registers the correct reply is
  `01 03 <2N> data crc16-LE`. The collector often returns only the first 20 (also 40
  or 80) bytes. The missing tail then arrives (A) glued in front of the next
  request's own reply, e.g. 33+113 bytes, or (B) alone as the retry's whole answer,
  e.g. `000000a367` (5 bytes) for a 10-register read, or (C) never. There is also a
  mixed case seen 2026-11-17: a 5-byte tail glued in front of a new 20-byte prefix.
  A complete, valid reply for the previous read can also arrive one slot late (wrong
  byte count, `unexpected_byte_count`).
- **Bare stray replies.** The collector sometimes pushes `01 03 6c ...` Modbus RTU
  replies outside the envelope. Some are cut off after about 20 bytes and the rest
  never comes (or comes late).
- **A daily event around 16:00 UTC** (see section 6).

Where it is handled:

| Concern | Code |
|---|---|
| Tail recovery, prefix hold and reassembly, retry policy | `custom_components/eybond_local/payload/modbus.py`: `recover_read_reply_tail`, `is_read_reply_prefix`, `reassemble_split_read_reply`, `ModbusSession.read_registers` (`_MAX_READ_ATTEMPTS = 3`), `_is_retryable_read_error`, `_note_recovered_read`. Order per attempt: normal parse, tail recovery, prefix reassembly, hold the prefix, log a WARNING, retry. First failure retries once; a second failure retries only while a cut-short prefix is held; timeouts retry once. |
| Bare/stray reply skipping, header resync | `custom_components/eybond_local/collector/transport/connections.py`: `_skip_cut_off_stray_rtu_reply`, `_resync_after_unrecognised_header` (`_HEADER_RESYNC_LIMIT = 2`, `_HEADER_RESYNC_IDLE_TIMEOUT = 0.05`; only after at least one valid frame this session) |
| Reader helpers | `collector/transport/common.py`: `take_available`, `discard_available`, `_find_trailing_eybond_frame` |
| Retry/reconnect orchestration | `custom_components/eybond_local/runtime/hub/refresh.py` |

Design intent worth keeping: **recover late bytes rather than close the socket**
(upstream's newer approach is the opposite: it retires the session; do not merge it
over ours without thought). Only verified data is used (slave id, function, byte
count and CRC must match).

## 5. Tooling, tests, releases (read before changing anything)

- **GitHub access is REST only.** GraphQL is blocked, so `gh pr create` and
  `gh pr merge` fail (HTTP 403). Use:
  `gh api repos/Barlows/ha-anenji-6200/pulls -f title=... -f head=BRANCH -f base=main -F body=@FILE`,
  wait on `gh api repos/Barlows/ha-anenji-6200/commits/SHA/check-runs`, then
  `gh api -X PUT repos/Barlows/ha-anenji-6200/pulls/N/merge -f merge_method=squash`.
  The session cannot create tags or releases directly (403).
- **Releases are automatic.** `.github/workflows/release.yml` runs on a push to `main`
  that changes `custom_components/eybond_local/manifest.json`: it reads the version,
  skips if the tag exists, renders notes from CHANGELOG with
  `tools/render_release_notes.py`, and creates tag and release (`--latest`, or
  `--prerelease` if the version has a `-`). So a docs-only change does **not**
  release. HACS installs the newest release, not the latest commit. Process and
  rules: [docs/maintainer/RELEASING.md](docs/maintainer/RELEASING.md).
- **To ship a fix:** branch; change code and tests; bump `manifest.json`; add a
  `## [X.Y.Z] - date` section to `CHANGELOG.md` (keep `[Unreleased]` above it and
  update the link references at the bottom, including
  `[Unreleased]: ...compare/vX.Y.Z...HEAD`); update README warning/reason tables if
  new log lines or reasons appear; PR; CI green; squash-merge; confirm the release
  with `gh api repos/Barlows/ha-anenji-6200/releases/latest`; refresh HACS
  (`ha_manage_hacs` with `update_information` for `Barlows/ha-anenji-6200`) and tell
  Sean to update and restart.
  `tests/test_release_consistency.py` requires the manifest version to equal the
  newest `## [x.y.z] - date` section.
- **Tests:** `python3 -m unittest discover -s tests -p "test_*.py"`. About 4 minutes,
  about 4,650 tests (19 skipped). Install what it needs with
  `pip install --break-system-packages -r requirements-test.txt`. Run it in the
  background, write output to a log, and wait on a marker line; the harness blocks
  `sleep N; ...` chains, so use `until grep -q ... ; do sleep 10; done`. `tests_ha/`
  needs Home Assistant and runs only in CI ("HA Runtime Tests 2026.9").
- **Transport baseline.** `tests/test_transport_module_boundaries.py` pins the count of
  class/function definitions across the transport family files (currently 273
  definitions, 213 unique) and a SHA-256 of the sorted `Kind:name` list. Adding or
  removing any function in those files fails it; recompute the three numbers by
  mirroring the test's `_definitions` logic (it excludes two
  `async_send_auxiliary_read` entries).
- **Docs checker:** `python3 tools/check_public_docs.py` validates local links and
  anchors in public docs; avoid em dashes in headings that are linked to.
- **CI jobs:** Validate (HACS validation, Hassfest, Quality Gate, HA Runtime Tests
  2026.9; HA Compatibility 2026.2 is usually skipped).
- **Commits and PRs** follow the attribution lines the session's own instructions
  give. Work in a feature branch; never commit straight to `main`.
- **Upstream:** read-only. `groove-max/ha-eybond-local` is public; clone shallow
  (`--depth 200`) to read it. The session cannot push there.

## 6. The live system and how to check it

Sean's Home Assistant is reachable through the **HA-MCP** tools when the session has
them (`ha_get_logs`, `ha_get_state`, `ha_get_history`, `ha_get_hacs_info`,
`ha_manage_hacs`, `ha_search`). If they are absent, ask Sean for log excerpts.

**Entities** (prefix `smg_6200`): `select.smg_6200_output_source_priority`;
`sensor.smg_6200_runtime_last_success_age` (should be ~0),
`..._runtime_reconnect_count` (resets to 0 on restart/reload),
`..._runtime_backoff`, `..._runtime_recovery_streak`,
`..._runtime_last_recovery_reason`, `sensor.smg_6200_load_power_filtered`.
His automations include Collector Freshness Watchdog, Collector Reconnect Flap
Monitor and a Policy Reconciler that ticks every 5 minutes.

**Primary health query:** `ha_get_logs(source="error_log", search="Runtime refresh
failed")`. Each such line is a **lost poll**. Zero lines is healthy. Also search
`collector.transport` (session closes, skips, resyncs) and `runtime.hub.common`
(timeouts, reconnects).

**Caveats:** the error-log window is only ~2,000 lines (about 1 to 1.5 days because of
the noise below), so for longer spans use `ha_get_history` on
`sensor.smg_6200_runtime_reconnect_count` (reconnects) or `source="system"` (dedup
counts since the last restart). If cursor-style `offset` values for older log pages
fail, use those two instead. The `eybond_local` logger is at WARNING, so the INFO
lines "Recovered ..." and "Reassembled ..." are hidden; raising its level to INFO for
a day would show how many reads are recovered. Do that only if Sean wants it.

**Normal background noise (not a problem):**

- `Modbus read answer rejected: unexpected_length:20 ... attempt=1` about 90 per day.
  The first reply was truncated and the same poll recovers it.
- `Inverter payload request timed out; retrying without collector reconnect`, a few
  per day.
- `Skipped a cut-off unwrapped Modbus RTU reply ... expected=113|93 arrived=20`
  (1.0.3 and later), a few per week. The connection stays up.
- `Dropped unrecognised bytes where a frame header was expected and resumed ...`
  (1.0.4), rare (once so far, 2026-11-06, 206 bytes dropped).
- `attempt=2` rejections, a few per week; with no `Runtime refresh failed` after them
  they were rescued by the third attempt.
- `Updating state for ... took 0.8 seconds` warnings from tooling buttons.

**Signals that matter:** any `Runtime refresh failed` line; `Closing collector session
...` (the reason is in the line, for example `collector_frame_length_invalid` or
`collector_frame_payload_timeout`); a rising reconnect count; the entities going
unavailable for more than a few seconds.

**The daily ~16:00 UTC event.** Every day the inverter request times out and
sometimes the collector drops and reconnects (`Collector transport failed during
payload retry: collector_disconnected; reconnecting`). The time creeps later by about
**16.6 seconds per day**: 15:58:27 on 30 Oct, 16:00:40 on 7 Nov, 16:03:24 on
17 Nov, so about 16:03:41 on 18 Nov. That points to a free-running 24-hour timer
inside the dongle or inverter, not Home Assistant or Sean's automations (those fire on
5-minute marks). It does not currently lose polls. If it ever starts to, the first
experiment is power-cycling the dongle to see whether the timer restarts.

## 7. Current status (2026-11-17)

- **Installed:** 1.0.4 (since 2026-11-03 about 15:00 UTC).
- **Lost polls before the fixes:** 20+ per day (20 Oct).
- **After 1.0.3** (21 Oct to 3 Nov): four lost polls. Two reads cut short twice
  (24 Oct 22:48, 26 Oct 16:26), one `collector_not_connected` (29 Oct 15:57), one
  session closed on a stray fragment `000000000000006c` (1 Nov 01:52).
- **After 1.0.4:** none observed in the log windows that could be read (4 to 17 Nov,
  with 12 to 16 Nov only visible through the reconnect counter). Fixes seen working
  on the unit: header resync fired once (6 Nov 09:15), the third attempt rescued
  reads cut short twice (7 Nov 02:47, 17 Nov 16:42), cut-off bare replies skipped
  several times, all without closing the session.
- **Reconnects:** the counter showed four in the six days to 17 Nov: three at the
  daily ~16:02 event and one at 22:20 on 15 Nov (cause not seen in the logs).
- **Brief unavailability:** the integration's sensors went unavailable for 10 to 15
  seconds nine times in those six days, each followed by a counter reset. They look
  like reloads or restarts; the cause was not determined.
- **Not addressed:** the 29 Oct `collector_not_connected`; the daily timer event;
  those brief unavailability blips. All are on the collector/inverter side or
  unexplained.
- **Recommendation at the time of writing:** make no changes; recheck every week or
  two, or when Sean reports a gap in his graphs.

## 8. Upstream tracking

Last checked **2026-11-17** at upstream `347352b`. Before that: `165e1cb` (12 Nov),
`5a912c7` (7 Nov). Nothing taken so far beyond ideas of our own. Decisions, so the
same commits are not re-litigated:

| Upstream | Decision | Why |
|---|---|---|
| `0d34892` ANJ-6200 output modes | skip | targets ANJ-6200-48PL (layout 2, model 0x2300); Sean's is the `anenji_op2_6200` / `smg_6200` profile |
| `b4e07c1` remove guessed SMG battery voltage limits | skip | affects 24 V and 4200 profiles; his is 48 V |
| `d3f7fad`, `c170121` Anenji 4200 controls, uncertain write evidence | skip | 4200 profile scoped |
| `0fb5e8f` SmartESS fallback registers | skip | SmartESS driver only |
| `6e6ecd4` CRLF AT replies | hold | only if that pattern appears in his logs |
| `3956d2c` await HA state publication after inverter writes | optional | cosmetic (entity updates immediately after a setting change); could be bundled into a future release |
| `dcad8ac` collector recovery stabilisation | skip | mostly cloud-learning; rewrites transport code we patched |
| `81a26c3`, `c02307c`, `306261b` (#89) late-fragment and desynchronised-session handling | skip | opposite strategy (close/retire the session); would undo 1.0.3/1.0.4 |
| Socket-storm series (#78, #81 and follow-ups) | skip | for collectors that open duplicate sockets; his reconnect count is normally 0 |
| `9649436` (#92) expire stale readings after 3 poll intervals (min 60 s) | skip | he already has `runtime_last_success_age` and his own watchdog; the daily event could flip sensors unavailable and trip his automations |
| New drivers and maps (MarsRock, Sandisolar, LVYUAN, SMX-II, short-ASCII, VPHB, BLE diagnostics, support archives) | skip | other hardware |

Check procedure: shallow-clone or fetch upstream, `git log --since=<last check>`,
read the changelog entries of anything touching `collector/transport/`,
`payload/modbus.py`, `drivers/modbus_smg` or `profiles/modbus_smg`, and compare
against section 4.

## 9. Open items and ideas (none approved)

- Optionally cherry-pick `3956d2c` (cosmetic) into a future release.
- Optionally raise the `eybond_local` log level to INFO for a day to count recovered
  and reassembled reads.
- Dongle experiments for the daily timer: check its Wi-Fi (signal, fixed IP,
  channel) or power-cycle it.
- A scheduled task that checks upstream and health weekly (offered, not set up).
- If `collector_not_connected` or header-fragment closes recur, look at the exact
  bytes in the surrounding log lines first; the fixes so far were each derived from a
  raw-byte log line.

---

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- Do not build or update the graph until the user explicitly approves the
  initial extraction. Once `graphify-out/graph.json` exists, update it at
  architectural batch boundaries rather than after every small code edit.
- Git hooks are intentionally disabled. Use the refresh and validation commands
  in `docs/maintainer/GRAPHIFY.md`; use `--force` after deletions or large refactors so
  stale symbols cannot survive in the graph.
