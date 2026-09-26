# Orchid synthetic launch note

Status: current synthetic policy, revision 3.

The launch latency threshold is 120 ms at p95. The error-rate threshold is 1.0 percent.

The operator MUST NOT launch when p95 latency exceeds 120 ms or when the error rate exceeds 1.0 percent. This prohibition is mandatory even when the average latency looks healthy.

The first observed failure in the frozen demo was `timeout while loading index segment`. It is evidence for the example only, not a production incident.
