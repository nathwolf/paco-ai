# Working on Paco

Read REQUIREMENTS.md, ARCHITECTURE.md, DATA_MODEL.md and ROADMAP.md before changing behavior. Work in end-to-end milestones and preserve the existing character assets.

Keep planning, reminder eligibility and permissions deterministic. Keep personality in presentation code. Inject clocks, connectors, notification delivery and model providers so tests can replay a day offline.

Use synthetic fixtures in tests and examples. Keep credentials, personal messages, databases and activity traces out of Git and logs. Test migrations on existing data. Exercise restart, replay, model outage, local time changes and user corrections when changing the relevant flows. Document which macOS and provider checks were actually run.
