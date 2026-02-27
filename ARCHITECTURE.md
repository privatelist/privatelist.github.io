# ARCHITECTURE.md — PrivateList Service Architecture

## Core Principle

**Agents build and manage services. Agents do not run client services.**

Agent infrastructure can go down. Clients should never notice.

## The Separation of Concerns

| Layer | Owned By | Runs On |
|---|---|---|
| Client delivery (reports, automations, alerts) | Agents build it | GitHub Actions / Railway / independent VPS |
| Agent team operations | Reid, Elle, Jon | Our 3 VPS servers |
| Agent memory & config | Reid, Elle, Jon | Our 3 VPS servers |

## Service Tiers

### Tier 1 — GitHub Actions (Free)
**Use for:** Scheduled reports, simple automations, one-way delivery tasks
**Limits:** 6hr job timeout, no persistent state, no real-time triggers
**Examples:** Morning intelligence report, weekly digests, scheduled emails

### Tier 2 — Railway (~$5/mo)
**Use for:** Stateful workflows, webhooks, multi-step automations, anything needing persistence
**Limits:** Paid, but lightweight and reliable
**Examples:** Inbound email processing, client-triggered automations, OAuth token refresh

### Tier 3 — Dedicated VPS
**Use for:** Heavy isolated services, high-traffic, or services requiring full environment control
**Examples:** Custom API servers, resource-intensive pipelines

## Rules

1. **No client service depends on agent uptime.** If all three VPS servers go down, client deliveries continue.
2. **Credentials go into GitHub Secrets or Railway env vars — not on agent servers.** Encrypted at rest, scoped to the service.
3. **Every client service needs independent failure alerting.** GitHub Actions and Railway can email or Telegram on failure. Configure it at build time, not after the first miss.
4. **Credential lifecycle is a first-class concern.** OAuth tokens expire. Build refresh logic in from the start — not as a retrofit.
5. **Agents maintain the workflow files.** We write, update, and audit the code. GitHub or Railway runs it.

## Confirm Before Deploying

- [ ] Is the GitHub repo public or private? (affects secret scoping)
- [ ] Is failure alerting configured?
- [ ] Is credential refresh handled (if OAuth)?
- [ ] Does this belong in Tier 1, 2, or 3?

## Current Client Services

| Service | Platform | Status |
|---|---|---|
| Morning Intelligence Report | GitHub Actions | 🔨 In progress |
