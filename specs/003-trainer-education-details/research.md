# Research: Trainer Education Details

## Decision 1: MVP strategy for institutions/courses

- **Decision**: Use `free-text + moderation` as the default path; do not require institution catalogs in MVP.
- **Rationale**: Fastest delivery with lowest operational complexity; covers Belarus-specific institutions and niche courses without waiting for taxonomy curation.
- **Alternatives considered**:
  - Mandatory controlled dictionary of universities/colleges/providers: rejected for MVP due to high maintenance cost and onboarding friction.
  - Hybrid with strict dictionary for formal education only: postponed; may be introduced later as optional suggestions.

## Decision 2: Required vs optional fields

- **Decision**: Keep exactly 3 required fields on create: `education_type`, `institution_name`, `program_or_title`.
- **Rationale**: Matches non-overload requirement and improves completion rate for first entry.
- **Alternatives considered**:
  - Require years on create: rejected (users often do not remember exact dates at first pass).
  - Require document upload on create: rejected for UX friction and higher support load.

## Decision 3: Moderation model and payload shape

- **Decision**: Keep status machine `pending_moderation -> approved|rejected`, but moderation payload to admin bot is a full trainer profile card (education included), not a separate education fragment.
- **Rationale**: Moderators need full context; this matches current operational flow and avoids fragmented moderation UX.
- **Alternatives considered**:
  - Separate education-only moderation card: rejected by product requirement.
  - Independent moderation queues per section: rejected as operationally expensive and confusing.

## Decision 4: Editing approved records

- **Decision**: Any trainer edit of an approved record creates a new pending moderation revision; last approved version remains visible publicly until new revision is approved.
- **Rationale**: Prevents unmoderated public changes and avoids profile regressions.
- **Alternatives considered**:
  - Revert existing record to pending immediately: rejected due to temporary disappearance of verified data.
  - Allow partial unmoderated edits for optional fields: rejected because moderation rules become inconsistent.

## Decision 5: Data model split

- **Decision**: Two entities: `trainer_education` (record state + public visibility) and `trainer_education_moderation_events` (immutable audit trail). Reuse existing profile moderation channel in admin bot.
- **Rationale**: Clean storage model while keeping moderation transport unified.
- **Alternatives considered**:
  - Single table with JSON history: rejected for query complexity and weaker reporting ergonomics.

## Decision 6: Performance and limits

- **Decision**: Limit records to 20 per trainer, default list pagination 10, optimized index `(trainer_id, status, updated_at desc)`.
- **Rationale**: Keeps profile reads fast and predictable under growth.
- **Alternatives considered**:
  - Unlimited entries: rejected as unnecessary for current product scale.

## Decision 7: Contract surface

- **Decision**: Keep integration within existing API and bot layers; no new external service.
- **Rationale**: Minimizes deployment risk and supports incremental rollout.
- **Alternatives considered**:
  - Separate moderation microservice: rejected as overengineering for current scope.
