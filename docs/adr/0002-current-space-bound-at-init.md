# Bind Current Space at client init, no runtime switching

A single Token can access multiple Spaces. We fix the Current Space when
the Client is initialised (resolved from config or `--space` flag) and
require re-initialisation to switch. This keeps every tool stateless and
avoids space-id parameters on every call. The cost is that cross-space
workflows (search in space A, create in space B) need two Client instances
or a restart. Rejected alternative: passing `space_id` to every tool —
verbose, error-prone, and rarely needed in practice.