# Security model

ClarityDesk is meant to audit **confidential** SMB documents — HR policies,
contracts, internal handbooks. The core promise is simple:

> A document's contents do not leave the local processing session.

## 1. Network-egress guard

The entire audit pipeline runs inside `security.network_guard()`, a context
manager that patches `socket.socket.connect` / `connect_ex` for its duration:

- **Loopback** (`127.0.0.1`, `::1`, `localhost`) is always allowed — local model
  servers and IPC keep working.
- **Every other destination is blocked** and raises `EgressBlocked`.
- The only way to permit an external host is to pass it explicitly:
  `network_guard(allow_hosts=["api.openai.com"])`.

This means an accidental (or malicious) attempt to upload the document — by any
library in the call stack — fails loudly instead of leaking data silently.

```python
from claritydesk.security import network_guard, EgressBlocked
import socket

with network_guard():
    socket.create_connection(("example.com", 443))   # raises EgressBlocked
```

The guard is fully removed on exit (verified by tests).

## 2. Local-only document handle

`security.LocalDocument.open(path)`:

- resolves and verifies the input is a **real local file** (no URLs/streams),
- enforces a **size cap** (default 100 MB) to bound resource use,
- computes a **SHA-256** fingerprint for the audit trail.

Document **content is never logged** — only the hash, page count, and
rule-level counts appear in reports.

## 3. Offline-by-default alt text

Alt text is generated **locally** by the heuristic provider (image pixel
analysis + surrounding caption/heading). No network is touched.

A cloud vision model is strictly **opt-in**:

1. set `CLARITYDESK_VISION=1` and provide `OPENAI_API_KEY`, and
2. the Orchestrator then allow-lists *only* the provider host in the egress
   guard for that run.

If the key is missing or the call fails, it falls back to the offline provider.
There is no silent cloud path.

## Threat model notes

- ClarityDesk does not execute embedded JavaScript or open external references in
  the PDFs it processes; it reads structure/text/images via PyMuPDF.
- Treat the egress guard as a strong in-process safeguard, not a substitute for
  OS/network-level isolation in hostile environments. For maximum assurance, run
  it inside a container with no outbound network.
