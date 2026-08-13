# ADR 0001: adapter boundary

Use a deterministic local adapter and explicit AWS adapter boundary. This keeps tests credential-free and makes cloud-specific behavior visible, while preserving the same upload, state, extraction, review, and audit contract.
