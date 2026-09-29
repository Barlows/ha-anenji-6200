# EyeBond Local Architecture

This document provides a high-level overview of the EyeBond Local integration architecture, its module dependencies, key design patterns, data flow, and concurrency model.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Home Assistant Core                          │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  Config Flow  │  │  Services    │  │  Entity Platforms        │  │
│  │  (onboarding) │  │  (controls)  │  │  (sensor, switch, etc.)  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘  │
│         │                  │                       │                │
│  ┌──────┴──────────────────┴───────────────────────┴─────────────┐  │
│  │                    EybondLocalCoordinator                      │  │
│  │              (runtime orchestration + polling)                 │  │
│  └──────┬──────────────────┬───────────────────────┬─────────────┘  │
│         │                  │                       │                │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌───────────┴──────────────┐  │
│  │  Connection  │  │   Runtime    │  │      Onboarding           │  │
│  │  (sessions,  │  │   (link,     │  │  (autodetection,          │  │
│  │   recovery)  │  │   transport) │  │   presentation)           │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────────┘  │
│         │                  │                                        │
│  ┌──────┴──────────────────┴─────────────────────────────────────┐  │
│  │                    Payload Layer                               │  │
│  │            (protocol framing and parsing)                      │  │
│  └──────┬────────────────────────────────────────────────────────┘  │
│         │                                                            │
│  ┌──────┴────────────────────────────────────────────────────────┐  │
│  │                    Driver Layer                                │  │
│  │         (probe, read, write orchestration)                     │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │  │
│  │  │  PI30   │ │  PI18   │ │  SMG    │ │  SRNE   │ │  MUST   │  │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │  │
│  └──────┬────────────────────────────────────────────────────────┘  │
│         │                                                            │
│  ┌──────┴────────────────────────────────────────────────────────┐  │
│  │              Protocol Catalogs (JSON)                          │  │
│  │  ┌──────────────────┐  ┌──────────────────────────────────┐   │  │
│  │  │  profiles/       │  │  register_schemas/               │   │  │
│  │  │  (capabilities,  │  │  (layouts, fields, enums,         │   │  │
│  │  │   conditions)    │  │   bit labels, model overlays)     │   │  │
│  │  └──────────────────┘  └──────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
         │
         │ TCP / UDP
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     EyeBond Collector / Inverter                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Module Dependency Graph

Dependencies flow strictly downward. Upper layers may import from lower layers; lower layers must never import from upper layers.

```
HA Core (config_flow, services, entities)
    │
    ▼
Coordinator (runtime orchestration)
    │
    ├──► Connection (session registry, recovery, strategy transition)
    │        │
    │        ▼
    │    Runtime Link (transport negotiation, callback triggers)
    │
    ├──► Runtime (hub, transport orchestration)
    │
    ├──► Onboarding (autodetection, presentation)
    │
    ▼
Payload (protocol framing and parsing)
    │
    ▼
Drivers (probe, read, write orchestration)
    │
    ├──► PI30, PI18, SMG, SRNE, MUST, etc.
    │
    ▼
Protocol Catalogs (JSON — profiles + register schemas)
```

**Key rule:** Dependencies flow downward only. `payload` must not import from `drivers`; `drivers` must not import from `runtime`; etc.

---

## Key Design Patterns

### 1. Layered Architecture

The system is organized into strict layers with one-way dependencies:

```
transport  →  payload  →  driver  →  profile  →  register schema  →  HA entities
```

Each layer knows as little as possible about the layers above and below it.

### 2. JSON-First Configuration

Hardware metadata (capabilities, conditions, presets, register layouts, enum tables) lives in JSON catalogs, not in Python code. This allows adding new inverter models without writing new Python drivers.

- `protocol_catalogs/profiles/` — capability groups, writable metadata, conditions, presets
- `protocol_catalogs/register_schemas/` — read-side layouts, fields, enums, bit labels, model overlays

### 3. Driver Registry Pattern

Drivers self-register via `drivers/registry.py`. Each driver implements a common interface (`drivers/base.py`) with methods for probe, read, and write. The registry discovers and selects the appropriate driver based on protocol detection.

### 4. Session Registry Pattern

`connection/session_registry.py` (`CallbackSessionRegistry`) is the single source of truth for "which config entry owns which inbound session." Identity is based on the full collector PN (durable), not peer IP or session ID (both transient).

### 5. One-Shot Callback Pattern

`callback_on_demand` sends exactly one UDP trigger per connect attempt, then bounded-waits for the inbound session. There is no continuous announcer loop.

### 6. Capability-Gated Writes

All write operations must go through declared, gated capabilities. Raw arbitrary write endpoints are prohibited.

### 7. Fixture-First Testing

Tests use captured fixtures rather than live hardware. The `fixtures/` package provides runtime fixture/replay helpers.

---

## Data Flow

### Read Path (Polling)

```
1. Coordinator polls the driver
2. Driver reads registers via the payload layer
3. Payload layer frames the request and parses the response
4. Driver returns a ReadResult with raw values
5. Coordinator maps raw values to entity states
6. HA entities update in the UI
```

### Write Path (Control)

```
1. User activates an entity (switch, button, etc.)
2. HA calls the service handler
3. Service validates the request against the capability profile
4. Driver encodes the write via the payload layer
5. Payload layer frames the write request
6. Driver sends the write and awaits confirmation
7. Write confirmation is validated (separate from command acceptance)
8. Entity state updates
```

### Discovery Path

```
1. Collector broadcasts UDP discovery
2. Collector transport receives the broadcast
3. Passive discovery extracts the collector PN
4. Onboarding presents detected devices to the user
5. User confirms and a config entry is created
6. Connection strategy is established (inbound or callback_on_demand)
```

### Connection Recovery Path

```
1. Connection failure is detected
2. Recovery contract is consulted
3. Strategy transition authority verifies identity (PN-based)
4. One-shot callback trigger is sent (if callback_on_demand)
5. New session is established and verified
6. Endpoint is reconciled (if integration_managed)
7. Normal polling resumes
```

---

## Threading/Concurrency Model

EyeBond Local runs entirely within Home Assistant's asyncio event loop. There are no threads.

### Async Concurrency

- **Single event loop.** All I/O is async. The integration uses `asyncio` primitives (locks, tasks, futures) for concurrency.
- **Coordinator lock.** The `EybondLocalCoordinator` uses a runtime-operation lock to prevent ordinary polling from racing with connection recovery or strategy transitions.
- **Session handoff.** TCP admission uses provisional stream slots (up to 100 in flight). Established collectors do not consume these slots.
- **Bounded waits.** All network operations have timeouts. Callback triggers bounded-wait for inbound sessions.

### Concurrency Safety Rules

- **Locks for shared mutable state.** Any state accessed by multiple async tasks must be protected by an `asyncio.Lock`.
- **Fail closed at socket boundaries.** Malformed frames close the socket and record a typed close reason. The reader never scans forward for convenient byte patterns.
- **No continuous loops in connect paths.** Callback triggers are one-shot per attempt.
- **Peer IP is never identity.** Only the full collector PN is durable identity. Peer IP is diagnostic/UDP-target only.

### Task Lifecycle

- Tasks are created for each async operation (polling, connection, discovery).
- Tasks are cancelled and awaited during shutdown.
- The TCP acceptor fences admission before disposing listener sessions.
- Cancellation of close waiters cannot abandon the drain of pending sessions.
