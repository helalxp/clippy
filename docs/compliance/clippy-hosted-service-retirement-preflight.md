# Hosted OpenShorts Service Retirement Preflight

> **Status:** Open; external service status requires owner confirmation.  
> **Last repository inspection:** 2026-11-19.  
> **Source baseline:** `61edcd5027e3f4e05c8019896e25af0e1cfa19f3`.  
> **Scope:** Separate the repository's Clippy v1 desktop extraction from the retirement of any existing OpenShorts Cloud service or its user data.

## 1. Why this preflight exists

Clippy v1 is a local-first Windows desktop product. The product decision is to remove the inherited hosted SaaS implementation from the Clippy v1 product. That decision does **not** establish that the existing OpenShorts Cloud service is already stopped, that no customers remain, or that production data can be deleted.

The current repository contains:
- A `cloud/` source tree under a separate OpenShorts Commercial License, not the root MIT licence.
- Billing, hosted auth, accounts, metering, managed provider keys, R2 storage, video archive, social profiles, lifecycle email, cloud analytics and account-erasure implementation.
- A cloud Compose override with PostgreSQL and production-style credentials.
- Privacy/subprocessor and retention documents dated 2026-09-04.
- An operations runbook describing encrypted PostgreSQL backups to an S3-compatible bucket.

The compliance documents explicitly describe OpenShorts Cloud, its data flows and production subprocessors. They are evidence that the repository was maintained for a real hosted service; they are not independent confirmation of its operational state on 2026-11-19. The owner must verify the current service state before external infrastructure or customer data is retired.

## 2. External systems and data obligations documented in this repository

This table is a repository-derived inventory. It is not a claim that every integration is still active today.

| System / provider | Role described by the current repository documentation | Retirement concern |
|---|---|---|
| Hetzner and Contabo | Production application/database hosting in Germany | Identify all live instances, snapshots, volumes, backups, domains and access owners before shutdown |
| PostgreSQL | Hosted user, subscription, usage, project, OAuth, API-key, onboarding and operational records | Inventory schema/data, legal retention, export/deletion obligations, restore capability and backup copies |
| Cloudflare R2 | Durable hosted clip/project storage and encrypted database backup destination | Identify buckets, objects, regions, access tokens, lifecycle rules, versioning/object lock and orphaned prefixes |
| AWS S3 | Optional UGC/public gallery and actor-image storage | Identify buckets, regions, objects, public access settings, credentials and downstream URLs |
| Stripe | Subscriptions, payments, webhooks and customer/invoice history | Cancel or transfer subscriptions safely; preserve records required by the applicable accounting retention policy; verify webhook endpoints and customer ownership |
| Aikount | Internal invoice/billing integration described in `cloud/billing.py` and the subprocessor register | Confirm whether there are invoice records, integrations or legal retention obligations outside the repository |
| Upload-Post | Connected social profiles and OAuth-token custody for hosted users | Confirm account/token custody, revoke or transfer connected profiles only through a controlled user-facing process |
| Google OAuth | Hosted account sign-in | Revoke/retire OAuth client credentials and callback URLs only after sign-in service shutdown and user notice |
| Google Gemini API | Managed processing and selected analysis features | Identify project/key owner, outstanding billing, terms, service-data retention and any remaining user-data processing |
| ElevenLabs and fal.ai | Dubbing, TTS and hosted AI UGC/video features | Confirm active keys/contracts, stored media, DPAs and deletion/retention obligations |
| Namecheap Private Email / SMTP | Magic links, transactional and lifecycle email | Preserve support, legal notices and customer communication during transition; retire credentials only after mail flow is stopped |
| Cloudflare DNS/CDN | Hosted website/API routing and traffic delivery | Identify active records, proxying, certificates, DNS ownership and rollback needs |
| OpenPanel | Self-hosted analytics/revenue mirror | Confirm whether events/profiles exist and deletion/retention expectations; Clippy v1 itself has a separate no-analytics decision |
| Telegram Bot API | Operational alerts | Remove bot/webhook credentials only when operational alerting has been transitioned |
| DataImpulse and static ISP proxies | Source-video download network path | Identify contracts, billing, account ownership and any credentials still used by a live service |

The source documents containing this inventory:
- `docs/compliance/subprocessors.md`
- `docs/compliance/retencion.md`
- `ops/README.md`
- `docker-compose.cloud.yml`
- `cloud/config.py`, `database.py`, `storage.py`, `videos.py`, `billing.py`, `account.py`, `auth.py`, `social_profiles.py`, `managed_keys.py`
- `.env.example` (placeholder variable names only; it does not establish whether any secret is configured in production)

## 3. Current retention and erasure behavior described in source

The repository's retention and account-erasure documents record several material obligations:

- Hosted working-job files and source uploads have separate cleanup rules.
- Free-tier durable R2 clips are described as expiring after seven days; paid-tier projects have a subscription/grace-period rule.
- User account erasure cancels live Stripe subscriptions first, purges the user's R2 prefix before deleting the database rows, attempts local job-file and Upload-Post profile cleanup, then removes user-owned database rows and sends a confirmation message.
- Stripe invoices/customer records are described as retained for six years.
- An account-erasure fingerprint row is described as retained for five years.
- Encrypted PostgreSQL backups are described as having a 30-day retention window.
- The documented subprocessor register names personal-data transfers and DPA/transfer safeguards that need to remain accurate until the hosted service and its data flows are actually retired.

These values are copied from the repository's dated compliance documents. They must be checked against the actual live configuration and legal advice before a shutdown plan is approved. Do not silently shorten retention or purge records by deleting code.

## 4. Backup and recovery preflight

`ops/README.md` states that `ops/pg_backup.sh` is not automatically run by the application. It must be installed and scheduled on the database host. It encrypts PostgreSQL dumps with age or GPG before upload to an S3-compatible bucket. The README also explicitly calls for a restore test.

Before retiring PostgreSQL, R2/S3 or hosting:
1. Identify whether the backup script is installed on the production host and whether its schedule is active.
2. Verify the actual backup destination and encryption recipient.
3. Confirm the private age/GPG recovery key is available to the authorised owner and is not stored on the production host.
4. Verify the current backup retention, bucket versioning/object-lock and deletion behavior.
5. Perform a controlled restore to an isolated test database and record the result.
6. Identify which records and invoices must be retained for legal/accounting purposes.
7. Decide whether customer project/media data is to be exported, migrated, returned, deleted or retained temporarily under a communicated closure policy.
8. Verify deletion across the primary database, R2/S3, application hosts, snapshots, backup copies, logs, third-party providers and social-account connections according to the actual obligations.

Do not delete the only usable copy of the database or customer media until the owner has approved and tested the export/retention/deletion plan. Do not destroy encryption keys before a required restore or retention period has ended.

## 5. Repository deletion versus live-service retirement

These are separate workstreams.

### Repository extraction

The Clippy v1 desktop payload currently does not copy the `cloud/` directory or `requirements-billing.txt`. The Tauri supervisor does not set `BILLING_ENABLED`. However, the shared `app.py` still contains conditional hosted routes/helpers, and cloud code is imported when the flag is enabled.

The safe source-code sequence is:
1. Map local routes and services that are mixed with cloud logic.
2. Extract/retain the local behavior and add contract tests.
3. Verify that the packaged Clippy application neither imports nor invokes the hosted subsystem.
4. Remove the now-disconnected hosted source from the Clippy v1 repository only after its separate licence/provenance and historical records are handled.
5. Keep required legal/accounting documents and historical audit evidence in an appropriate archive; do not delete them merely to make the repository look clean.

### Live infrastructure retirement

This requires an explicit service owner and may require work outside GitHub:
- Customer communications and account/export paths.
- Subscription cancellation, refunds or transfer.
- DNS, hosts, databases, buckets, backups and snapshots.
- OAuth/social credentials and third-party API keys.
- DPAs, subprocessors, privacy notices and legally required records.
- Billing/tax/invoice records.
- Provider contract cancellation, final invoices and access revocation.
- Final data deletion evidence and a record of any data retained under law.

A Git commit deleting `cloud/` or a Docker Compose file does not stop a host, revoke a key, cancel a subscription or delete an object in R2.

## 6. Owner verification checklist

The service owner must answer these before Phase 3's destructive hosted-code removal is approved:

- [ ] Is `openshorts.app` / OpenShorts Cloud still live or accepting users?
- [ ] Are any accounts, paid/free subscriptions, outstanding invoices or refunds still active?
- [ ] Is any customer project/media data still held in PostgreSQL, R2, S3, server disks, snapshots or backups?
- [ ] Are production Hetzner/Contabo hosts or other hosting environments still running?
- [ ] Is the PostgreSQL backup job installed, scheduled and successfully restorable? Where is its recovery key held?
- [ ] Are Stripe webhooks, Google OAuth callbacks, SMTP, Upload-Post, Gemini, ElevenLabs, fal.ai, proxies, OpenPanel, Telegram and Cloudflare credentials still in active use?
- [ ] Does the existing privacy policy/subprocessor register still describe a live service, or has a closure/transfer notice already been issued?
- [ ] What customer notice, export, account closure, subscription cancellation, data deletion and legal retention process is required?
- [ ] Who is authorised to approve and execute provider shutdowns and final data deletion?

Answers should be recorded without publishing secrets, customer identifiers or personal data in this repository.

## 7. Phase gates

### Before Phase 2 backend extraction
- Identify which hosted systems and service contracts are genuinely active.
- Preserve an auditable copy of the current cloud/service source and historical operational documentation.
- Keep cloud deletion out of scope while the local API separation is underway.

### Before Phase 3 hosted-source removal
- Local API behavior is extracted and tested.
- The owner confirms the live-service state.
- If a hosted service exists, its customer/data/retention transition is completed or has a separately approved schedule and owner.
- Historical legal/operational records are archived appropriately.
- No cloud-only dependency remains in the packaged Clippy desktop workflow.

### Before external infrastructure shutdown
- Customer and legal obligations are satisfied.
- Verified backup/export and recovery requirements are met.
- Subscription, provider, domain, OAuth and object-store dependencies have been retired in a controlled order.
- Final deletion and provider shutdown evidence is recorded by the service owner.

**Current status:** unresolved. The repository documents a hosted service and operational data obligations, but this Git review cannot verify the actual state of production hosts, accounts, subscriptions, buckets, backups or customer records. Explicit owner confirmation is required.
