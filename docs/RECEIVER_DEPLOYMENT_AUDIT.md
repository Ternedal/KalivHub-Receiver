# Receiver deployment and contract audit

Audit date: 2026-10-23. Scope: inspected repository `index.html`, `.github/workflows/pages.yml`, and README. **Static inspection only**; no GitHub Actions execution, Cast session or physical Nest Hub validation was performed for this audit.

## Confirmed from repository files

- Receiver is served from a static `index.html` page; page markup includes display tiles and responsive styles.
- GitHub Pages workflow triggers on pushes to `main` and manual dispatch. It uses `actions/checkout@v4`, `actions/configure-pages@v5`, `actions/upload-pages-artifact@v3` and `actions/deploy-pages@v4`.
- The workflow runs `node tests/receiver-static.cjs` before uploading the site. A successful deployed build still needs to be checked on the actual published URL.
- The README specifies the custom Cast namespace `urn:x-cast:dk.kalivhub.lab`, snapshot version 1 and display-only semantics. These are documented contracts, **not revalidated here against every JavaScript handler**.
- The receiver must not receive Home Assistant tokens or control authority.

## Operational acceptance

1. Confirm the static test exists and passes on the exact PR commit.
2. Verify Pages is enabled for GitHub Actions and the deployed HTTPS URL serves the intended commit.
3. Confirm the Cast developer registration uses that exact HTTPS URL and namespace.
4. Exercise a real Nest Hub session with valid, invalid, duplicate and stale snapshot messages.
5. Verify reconnection, offline timeout, long entity names, room grouping and unavailable states.
6. Confirm secrets and private entity values never appear in the public site or payload.

## Known limitations

- Static UI and browser tests do not prove Nest Hub touch, microphone or full Cast interoperability.
- This audit does not establish production readiness or a successful release.
- See [integration acceptance](INTEGRATION_ACCEPTANCE_2026-10-23.md) and [ecosystem map](KALIV_ECOSYSTEM.md).
