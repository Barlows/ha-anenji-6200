# Changelog — EyeBond Local SC

What has changed in **this fork**, [Barlows/ha-anenji-6200](https://github.com/Barlows/ha-anenji-6200),
newest first. It is a build of
[groove-max/ha-eybond-local](https://github.com/groove-max/ha-eybond-local) kept
running against one real unit: an **Anenji / Aninerel SMG 6200** (firmware 7904)
behind an EyeBond Wi-Fi collector.

How to read it:

- **Releases are versioned.** This fork follows [Semantic Versioning](https://semver.org/):
  `MAJOR.MINOR.PATCH`. A patch release (`1.0.1`) is a fix, a minor release (`1.1.0`)
  adds something, and a major release (`2.0.0`) changes something you would have to
  react to. Each version has a section below, a git tag `vX.Y.Z`, and a
  [GitHub release](https://github.com/Barlows/ha-anenji-6200/releases) whose notes are
  that section. HACS offers those releases, so you can install any of them (see
  [Install](README.md#install)).
- Work that has been merged to `main` but not released yet is listed under
  **Unreleased**.
- The integration's `manifest.json` version is this fork's version, not upstream's
  (upstream's was `0.3.0-beta.5` when this fork started versioning). The version is
  also shown in the integration's diagnostics and in support archives.
- Anything described as "confirmed" was seen on the real unit. Anything else is
  said to be untested.
- Upstream's own release history is not repeated here. It is carried through
  unchanged in [UPSTREAM_CHANGELOG.md](UPSTREAM_CHANGELOG.md).

---

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-10-09

The first versioned release. It is the state of the fork after the work that ended
the collector reset cycle on the SMG 6200, and the baseline to roll back to or
forward from. The day-by-day account, with the log lines that identified each
cause, is in the [history before 1.0.0](https://github.com/Barlows/ha-anenji-6200/blob/main/CHANGELOG.md#history-before-100).

### Fixed

- **Stray Modbus replies no longer close the collector session.** The collector
  pushes bare Modbus RTU read replies outside any EyeBond frame. Upstream closes
  the session on one; on this unit that was a reset about every 3.5 minutes. A
  reply is now skipped only when its length is consistent **and its Modbus CRC
  verifies**, including the 88-byte case that happens to decode as a valid EyeBond
  header. Anything that fails the CRC, is truncated, or is genuinely malformed
  still closes the session. (#11, #13)
- **Register reads retry once on a wrong slave id or function byte**, as they
  already did for short, bad-CRC and wrong-length answers. (#14)
- **Collector Retained Disconnect Reason now survives a reconnect.** It used to
  read `none` through every redial. (#10)

### Added

- **Collector Stray Modbus Replies Skipped** diagnostic sensor, also included in
  the collector summary and the support bundle. (#11)
- **Raw bytes of every rejected Modbus read answer are logged** (first 64 bytes,
  length, register, attempt), and the incomplete-frame warnings carry their header
  bytes, so an odd answer can be diagnosed from the log alone. (#12, #15)
- The SMG 6200 firmware 7904 catalog entry, Solar-Utility-FeedIn output priority
  and Output 2 Overload fault code this fork was started for.

### Changed

- **Collector Last Disconnect Reason** reads `none` while the session has no
  fault, instead of `unavailable`. (#14)
- Collector metadata polling no longer sends the nearby Wi-Fi scan query
  (`INTPARA49`). Same change as upstream's `e5b4a2d`. (2026-10-06)
- The integration's documentation and bug-report links point at this fork, and
  the Ukrainian README (a translation of upstream's) is gone. (#17)
- The README and changelog were rewritten for this fork. (#16)

### Known issues

- Roughly one failed poll every couple of hours remains (a stray reply landing in
  a poll's slot, or a wrong-length answer). It is retried once and costs one
  refresh.
- The collector's Wi-Fi occasionally resets the TCP connection on its own, and a
  stray reply can be cut off mid-flight. Both close the session and it
  reconnects. Seen twice in the first day after the fix.

## [History before 1.0.0]

Everything below happened before versioning started, so it is grouped by day
instead of by version, and names the pull request and commit where there is one.
These entries are the detail behind the 1.0.0 summary above.

### 2026-10-09

#### Changed

- **Documentation and bug-report links now point at this fork.** The integration's
  `manifest.json` (`documentation` and `issue_tracker`) named upstream, so the
  "Please create a bug report at …" line Home Assistant prints for slow entity
  updates sent people to the wrong tracker.
- Removed the Ukrainian README, which was a translation of upstream's README and no
  longer matched this fork's. Upstream still has it.

#### Diagnostics

- **Rejected register reads now log what actually arrived.** Every Modbus read
  answer the integration rejects (`unexpected_slave_id`, `unexpected_function`,
  `unexpected_length`, bad CRC and so on) is logged at WARNING with the first 64
  bytes received, their length, the register address and count, and which attempt
  it was. The "incomplete unwrapped Modbus RTU reply" warning also carries its
  header bytes. Logging only: nothing about retries or session handling changed.
  (#15, `9d23494`)

---

### 2026-10-08 (ending the collector reset cycle)

The headline problem on this unit: the collector's session was being dropped about
every 3.5 minutes (`collector_disconnected`, sometimes 11 resets in 40 minutes),
and the "retained disconnect reason" sensor never showed why. Both are addressed
below. The log lines quoted are the ones that identified each cause.

#### Fixed

- **Stray Modbus replies no longer close the session.** The collector keeps
  pushing bare Modbus RTU read replies (`01 03 <byte count> data CRC`) outside any
  EyeBond frame, in rotating sizes (0x14, 0x18 and 0x6c data bytes, plus a 7-byte
  one-register form). Upstream deliberately closes the session on one of these
  (its issue #39), and on this unit that was the reset cycle. A reply is now
  recognised only when its length is consistent **and its Modbus CRC verifies**;
  exactly those bytes are skipped and the session stays up. A look-alike that
  fails the CRC, a truncated reply, or any genuinely malformed header still closes
  the session, and a real EyeBond frame that merely starts with similar bytes is
  handed back to the normal parser untouched. This reverses upstream's
  close-on-bare-reply behaviour on purpose, so that test was rewritten and a
  bad-CRC variant added to keep the close path covered. (#11, `6a9394c`)
- **…including replies that look like valid EyeBond headers.** One remaining
  reset logged `incomplete frame payload … tid=259 fc=19 expected=775`. The
  captured header bytes `0103580003090d13` turned out to be an 88-byte bare reply
  whose data happens to decode as a header that passes every check, so the first
  fix never examined it and the reader waited for a 775-byte payload that never
  came. Header-valid frames longer than a CRC-checkable reply candidate are now
  probed: a CRC-verified reply is skipped, anything else is handed back unchanged,
  and a frame no longer than the candidate is never delayed. Covered by tests for
  the captured shape, a bad-CRC variant, a truncated reply, and genuine long and
  short frames that open with the same bytes. (#13, `6c4a4a8`)
- **Register reads retry once on a wrong slave id or function byte.**
  `unexpected_slave_id:0` and `unexpected_function:0` were costing a whole poll
  refresh a few times an hour; they are what a stray reply looks like when it lands
  in a poll's slot. A read now repeats once, as it already did for short, bad-CRC
  and wrong-length answers. A genuinely wrong slave id still fails after the single
  retry, and exception replies are never retried. (#14, `d439c75`)
- **Collector Retained Disconnect Reason now actually retains the reason.** The
  listener dropped the closed session's connection object from its indexes, and
  the redial got a fresh one, so the sensor read `none` through every reconnect.
  The listener now keeps the last real reason per collector (by IP and PN) and
  the framed transport restores it, with a regression test that drives the real
  drop-and-redial path. The AT-text transport is not covered. (#10, `3855600`)

#### Added

- **Collector Stray Modbus Replies Skipped** diagnostic sensor: how many stray
  replies the current session has skipped. It restarts from 0 with every new
  session, so a counter that keeps climbing means the fix is working and a drop
  to 0 means the session was replaced. Also included in the collector summary and
  the support bundle. (#11)

#### Changed

- **Collector Last Disconnect Reason** reads `none` while the current session has
  no fault, instead of `unavailable`, matching the Retained Disconnect Reason
  sensor. (#14)

#### Diagnostics

- The "incomplete frame payload" warning now includes the decoded header bytes and
  whether its first seven bytes form a CRC-valid Modbus reply (`header=…`,
  `rtu7_crc_valid=…`). Logging only. (#12, `8be68f2`)

#### Result on the real unit

Measured on the SMG 6200 (as of 2026-10-09 afternoon):

| | Before | After |
|---|---|---|
| Collector session drops | about every 3.5 minutes | none for 14 h 51 min, then one dongle-side TCP reset (13:22) and one cut-off stray reply (13:52) |
| Stray replies skipped | — | 160 in a single overnight session |
| Single-poll failures (`unexpected_*`) | roughly hourly | roughly every two hours |

The remaining single-poll failures and the two afternoon drops are not fixed;
they look like Wi-Fi hiccups and the occasional stray reply that lands in a poll
slot. They cost one refresh each, and the raw-byte logging above was added to find
out exactly what arrives.

#### Reviewed, not adopted

- PR #9 ("Release/v0.3.0 code quality improvements", a large
  `ConnectionManager` / `OwnerCounter` / `RouteReservationManager` refactor) was
  reviewed against current `main`, found to need two regression fixes to integrate
  safely, and **closed without merging**: the risk outweighed the benefit for a
  fork whose job is to keep one device stable. The integration attempt is kept on
  the `integrate-pr9` branch for reference.

---

### 2026-10-06

#### Changed

- **Collector metadata polling no longer sends the nearby Wi-Fi scan query
  (`INTPARA49`).** A scan makes the dongle's radio leave its channel on every
  metadata cycle, a plausible contributor to the `collector_disconnected` and
  malformed-frame resets seen here. This is the same change upstream made in
  `e5b4a2d`, taken on its own; upstream explicitly does not claim it fixes
  connection interruptions, and neither does this fork. Connected SSID and signal
  strength are still read, and Wi-Fi setup still scans on demand over Bluetooth.
  The disabled-by-default **Collector Wi-Fi Scan List** diagnostic sensor remains
  defined but no longer receives a value.

---

### 2026-09-26 — test suite

- **Documented the test requirements.** The unit suite needs the two libraries in
  `requirements-test.txt` (`aiohttp`, `voluptuous`); both are imported at module
  scope by production modules the stub-based suite cannot fake. Running without
  them left a half-initialised set of `homeassistant.*` stubs behind and produced a
  misleading spread of order-dependent failures, none of which pointed at the
  missing library. With both installed the suite was fully green at the time
  (4,596 tests, 0 failures). No production code changed.
- **Stopped the stub test harnesses leaking test doubles into real modules.**
  `ensure_module()` only consulted `sys.modules`, so the first test to ask for a
  not-yet-imported name installed an empty module that shadowed the real one for
  the rest of the process. It now tries the real import first. That exposed a
  second leak, where the coordinator harness overwrote functions on
  `drivers.registry` and never restored them; they are now captured once and
  restored via `addClassCleanup`. Full-suite failures went from 46 to 22 (12 of
  the remainder were only a missing `aiohttp`), verified by diffing the failure set
  against unmodified `main`.

### 2026-09-25 — diagnostics and fork branding

- **Transport-fault sensors and clearer service errors.** Added **Collector
  Callback Wire Framing**, **Collector Last Disconnect Reason**, **Collector
  Management Adapter** (+ provenance) and **Observed Session Protocol**
  diagnostic sensors. Failed `eybond_local` service calls (reboot collector, set
  endpoint, start/stop proxy capture and so on) now raise an actionable error with
  a plain-language hint instead of a bare exception, and unsupported management
  actions fail fast with a clear code.
- **Disconnect reason survives a reconnect.** `last_disconnect_reason` was reset
  to empty on every new session, which could erase the exact fault before it was
  read. Added `retained_disconnect_reason`, set at both disconnect sites and
  carried into the snapshot, session inventory and support bundle. `last_error`
  and the new sensor report `none` on a healthy system instead of `unavailable`.
  (Superseded in part by the 2026-10-08 fix above, which made the retained value
  genuinely survive.)
- **Recognise unwrapped Modbus RTU replies in the malformed-frame log line.**
  This was the first sign of what the 2026-10-08 fix later addressed: header
  failures that begin with a slave address, a read function code and a plausible
  byte count are real RTU replies outside the EyeBond envelope, not wire
  corruption. Diagnostics only at the time.
- **Test-suite fixes.** Seven test modules imported helpers above the `sys.path`
  guard meant to make that work, one detection test drove the real scan path with
  multi-second deadlines (9 s for one test), and an unbounded `asyncio.Event` wait
  could hang the whole suite. The suite went from hanging past 15 minutes to
  finishing in about 3.
- Pointed the README and changelog at this repository and named it as a fork.

### 2026-09-13 — SMG 6200 firmware 7904 re-applied on upstream

The original SMG 6200 work (below, July) was rebuilt on top of upstream's then-current
`main` and extended:

- Exact-fingerprint catalog entry `smg_6200_fw7904` for firmware revision 7904
  (`model_code 0x7904`, layout 11, Aninerel / Anenji 6200 dual-output), bound to
  the `anenji_op2_6200_full` control surface.
- **Solar-Utility-FeedIn (SUF)** output-source-priority option (first added in July)
  and an **Output 2 Overload** fault code in the classic SMG RS232 V1 profile and
  register schema.
- Hardware-tested support notes for `automatic_mains_output_enabled`,
  `output2_cutoff_soc` and `output2_overload_threshold` on that exact
  model and firmware, from local write testing on the real inverter.
- Removed a dead `output_power < 0` branch and clarified a deliberately reverted
  Output 2 fix note; regenerated the model-catalog docs.

### 2026-07-13 to 2026-07-20 — where this fork started

The first commits, made directly against the SMG 6200:

- Added the SMG 6200 inverter entry, new Solar-Utility profiles, a
  Solar-Utility-FeedIn output-source-priority option, and validation of output power
  against the model's rated power limits.
- Added tested-status and support notes for the Output 2 settings and battery SOC
  register, and a new error code for a battery-connection fault.
- Renamed the display name from **EyeBond Local** to **EyeBond Local SC**.

---

For everything before the fork point, see
[UPSTREAM_CHANGELOG.md](UPSTREAM_CHANGELOG.md).

[Unreleased]: https://github.com/Barlows/ha-anenji-6200/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Barlows/ha-anenji-6200/releases/tag/v1.0.0
