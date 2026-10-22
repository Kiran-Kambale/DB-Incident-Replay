# Roadmap

Status refers to this portfolio prototype, not an enterprise product.

## Completed / demonstrated locally

- [x] Local PostgreSQL lab and synthetic `demo_accounts` table.
- [x] FastAPI-based local API and browser dashboard.
- [x] Live diagnostic data for supported activity/blocking checks.
- [x] Manually reproducible row-lock incident and independent SQL verification.
- [x] Initial lock-related investigation guidance.

## Next milestones

- [ ] Save timestamped diagnostic snapshots with explicit collection time and errors.
- [ ] Build an incident list/history view comparing snapshots.
- [ ] Export a sanitized incident report as JSON/Markdown.
- [ ] Add tests for API endpoints and diagnostic query results.
- [ ] Add structured error handling and clear UI loading/empty/error states.
- [ ] Add query-plan guidance for user-selected, sanitized SQL in a local lab.
- [ ] Add connection pressure detection validated against server-wide statistics.
- [ ] Add a two-node replication lab before claiming replication-lag detection.
- [ ] Add automated checks/linting and CI.
- [ ] Complete security review before any non-local deployment.

## Out of scope until properly designed

- Automatically terminating sessions or changing customer databases.
- Connecting to production systems without explicit authorization and security review.
- Claiming guaranteed root cause from heuristics alone.
