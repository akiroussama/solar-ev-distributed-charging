# Security Policy

This repository contains research simulation code. It does not provide a
production V2I/I2I security protocol.

## Supported Reports

Please report vulnerabilities involving:

- request validation bypasses in the simulated `TRUST-EV` layer;
- replay-detection failures;
- unsafe defaults that could mislead experimental conclusions;
- dependency or CI configuration issues.

## Non-Goals

The current implementation does not claim:

- production-grade cryptography;
- real vehicle identity management;
- real charging-station deployment security;
- guaranteed prevention of all attacks.

Security mechanisms are modeled so they can be measured experimentally and
extended toward stronger protocols.

