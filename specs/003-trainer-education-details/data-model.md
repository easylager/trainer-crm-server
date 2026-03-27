# Data Model: Trainer Education Details

## Entity: TrainerEducation

Represents trainer-provided education item (formal education or course/certificate) with moderation status.

### Fields

- `id` (UUID, PK)
- `trainer_id` (UUID, FK -> trainer)
- `education_type` (enum: `formal_education`, `course_or_certificate`) - required
- `institution_name` (varchar(160)) - required
- `program_or_title` (varchar(180)) - required
- `degree_level` (enum nullable: `higher`, `master`, `secondary_special`, `vocational`, `other`)
- `country` (varchar(64), nullable)
- `city` (varchar(64), nullable)
- `start_year` (smallint, nullable)
- `end_year` (smallint, nullable)
- `is_in_progress` (bool, not null, default `false`)
- `document_url` (varchar(512), nullable)
- `moderation_status` (enum: `pending_moderation`, `approved`, `rejected`, not null)
- `moderation_comment` (varchar(500), nullable; trainer-visible reason on reject)
- `approved_snapshot` (bool, not null, default `false`) - true when this version is publicly visible
- `created_at` (timestamp with tz, not null)
- `updated_at` (timestamp with tz, not null)
- `approved_at` (timestamp with tz, nullable)
- `approved_by_admin_id` (UUID, nullable)
- `supersedes_id` (UUID nullable, self-FK) - links edited pending revision to prior approved record

### Validation Rules

- Required on create: only `education_type`, `institution_name`, `program_or_title`.
- `institution_name`, `program_or_title` must be trimmed, length >= 2.
- `start_year`/`end_year` in range `[1950, current_year + 1]`.
- If both years provided then `start_year <= end_year`.
- If `is_in_progress = true`, `end_year` may be null.
- `document_url` must be http/https URL if provided.

### Indexes

- `idx_trainer_education_trainer_status_updated` on (`trainer_id`, `moderation_status`, `updated_at desc`)
- `idx_trainer_education_pending` on (`moderation_status`, `created_at asc`) for moderation queue

### State Transitions

- Create by trainer: `pending_moderation`
- Approve by admin: `pending_moderation -> approved` and `approved_snapshot=true`
- Reject by admin: `pending_moderation -> rejected` with mandatory `moderation_comment`
- Edit approved record by trainer: new row in `pending_moderation` with `supersedes_id=<approved_id>`; previous approved row remains visible until new approval

## Entity: TrainerEducationModerationEvent

Immutable audit trail for moderator decisions for education changes processed in full-profile moderation flow.

### Fields

- `id` (UUID, PK)
- `trainer_education_id` (UUID, FK -> trainer_education)
- `admin_id` (UUID, FK -> admin user)
- `decision` (enum: `approved`, `rejected`)
- `reason` (varchar(500), nullable for `approved`, required for `rejected`)
- `created_at` (timestamp with tz, not null)

### Validation Rules

- `reason` required when `decision = rejected`.
- Event row inserted atomically with education status update.

## Integration Rule: Full Profile Moderation Payload

- Education changes **do not** produce a standalone moderation card in admin bot.
- When education is created/edited by trainer, system marks relevant education rows as `pending_moderation` and triggers existing full trainer profile moderation card.
- Admin decision in the profile moderation flow updates education statuses for affected pending rows consistently.

## Optional Entity (Future): EducationCatalogItem

Used for non-blocking autocomplete suggestions.

### Fields

- `id` (UUID, PK)
- `name` (varchar(160), unique within category+country)
- `category` (enum: `university`, `college`, `provider`)
- `country` (varchar(64))
- `is_active` (bool, default true)

### Rule

- Catalog is advisory only; trainer free-text input remains allowed.
