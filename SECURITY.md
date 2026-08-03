# Security Policy

This repository is a research prototype and is not approved for processing protected health information or making clinical decisions.

## Supported scope

Security reports should concern the current public release. Historical local packages are not supported.

## Reporting

Use the GitHub repository's private security-advisory feature when available. Otherwise open an issue containing only non-sensitive reproduction details. Never include patient data, credentials, private endpoints, access tokens, or institution-identifying logs in a report.

## Deployment boundary

The included stdio and localhost HTTP interfaces are for reproducibility testing. Authentication, authorization, audit retention, network isolation, secret management, rate limiting, and clinical change control require an independent deployment review.
