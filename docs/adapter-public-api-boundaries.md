# Adapter package public API boundaries

## Decision

Adapter package roots are read-side entry points. They may export read-only
transports, collectors, readers, models, state types, normalizers, and
configuration needed by those components. They do not import or re-export an
`operation` module.

Operation requests, capability snapshots, planners, gates, dispatch receipts,
and operation adapters must be imported from the explicit operation module:

```python
from hedp.adapters.bravia.operation import BraviaPowerRequest
from hedp.adapters.miele.operation import StartScheduledProgramRequest
from hedp.adapters.sakura.operation import SakuraStartChargingRequest
from hedp.adapters.ecocute.operation import EcoCuteSetCommand
```

EcoCute follows the same boundary for frame builders. `build_get_request`
remains available from `hedp.adapters.ecocute`; Set/SetC builders are available
only from `hedp.adapters.ecocute.echonet` and are not part of the read-side
package-root API.

## Why this is intentionally incompatible

Importing an Adapter package for observation must not initialize or advertise
operation capabilities. A package-root re-export makes a read-only caller,
plugin discovery process, or documentation generator see operation types even
when it never opted into the operation boundary. Keeping the dependency
direction one-way also prevents a reader, collector, normalizer, transport,
state, or model module from acquiring operation dependencies accidentally.

This change deliberately removes the previous package-root operation imports
for BRAVIA, Miele, and Sakura, and the EcoCute SetC builder export. Code using
those imports must migrate; no compatibility alias is retained because an
alias would preserve the unsafe ambiguous boundary.

## Migration

Change only the import path. Type names and behavior remain unchanged.

```python
# Before
from hedp.adapters.miele import MieleOperationGate

# After
from hedp.adapters.miele.operation import MieleOperationGate
```

Read-side imports continue to use the package root:

```python
from hedp.adapters.miele import MieleReader
from hedp.adapters.ecocute import EcoCuteReadOnlyCollector
```

Applications should keep operation imports close to the explicitly authorized
execution composition root. Read-only modules must not import an operation
module indirectly to recover the old spelling.

## Enforcement

The cross-Adapter boundary test parses every Adapter package root and every
non-operation Adapter module. It rejects operation imports outside an explicit
`operation.py`, and checks the intentionally removed BRAVIA, Miele, Sakura,
and EcoCute symbols at runtime.

The same test rejects static Darwin-only imports, POSIX-only modules, Windows-
only modules, OS-specific path classes, Unix permission/identity calls,
Unix-only signal APIs, launchd/AppleScript references, and fixed host paths.
Portable `pathlib.Path`, UTC timestamps, standard TCP/UDP sockets, and bounded
HTTP clients remain allowed.

Several collectors use `ZoneInfo("Asia/Tokyo")`. Linux distributions normally
provide the IANA timezone database through the operating system; Windows may
not. The project therefore declares a conditional `tzdata` dependency for
Windows, and the boundary test fails if Adapter `zoneinfo` use exists without
that dependency. Deployment still must not assume launchd, POSIX file modes,
Unix signals, mDNS availability, or a fixed filesystem layout.
