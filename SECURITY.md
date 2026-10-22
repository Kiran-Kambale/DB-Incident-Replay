# Security Policy

## Scope

This is a learning/portfolio prototype intended for a local synthetic PostgreSQL lab. It is not production-ready and should not be exposed to the internet or connected to customer/employer production systems.

## Reporting a concern

Please open a GitHub issue for non-sensitive reproducible problems. Do not post passwords, tokens, connection strings, private hostnames, customer data, or unredacted production logs. For sensitive issues, contact the repository owner privately through an available GitHub contact channel.

## Current safeguards and limitations

- The intended bind address is `127.0.0.1`.
- Database credentials belong in local `.env`, which must not be committed.
- Use a dedicated reader role and synthetic data.
- Review the source and permissions before running it anywhere beyond a local lab.
- No production security audit or deployment hardening is claimed.
