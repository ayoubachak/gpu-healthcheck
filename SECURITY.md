# Security and safe use

- Never connect a visibly damaged 16-pin connector. Shut down, unplug, then inspect.
- Use a PSU and cables rated for the card. Stress tests can expose a marginal PSU, so a
  crash does not automatically mean the GPU is faulty.
- The kit never changes clocks, voltage, fan curves, firmware or power limits.
- Download third-party tools from their official release pages and check licences.
- `results/` and `external/` are git-ignored. Logs can contain GPU serials, UUIDs,
  hostnames and seller details: redact before publishing.
- A zero-error run cannot certify remaining lifespan or protect against fraud.
- GitHub Actions has no GPU. A green CI run validates the code, not any hardware.
