# Contract: Trainer Education + Full-Profile Moderation

## 1) API Contract (trainer profile)

### GET `/api/trainers/{trainer_id}/education`

- **Purpose**: Return trainer education list for owner/admin with moderation details.
- **Response 200**:

```json
{
  "items": [
    {
      "id": "uuid",
      "education_type": "formal_education",
      "institution_name": "БГУ",
      "program_or_title": "Психология",
      "degree_level": "higher",
      "start_year": 2016,
      "end_year": 2020,
      "is_in_progress": false,
      "document_url": null,
      "moderation_status": "approved",
      "moderation_comment": null,
      "approved_at": "2026-03-24T10:00:00Z",
      "updated_at": "2026-03-24T10:00:00Z"
    }
  ]
}
```

### POST `/api/trainers/{trainer_id}/education`

- **Purpose**: Create education entry by trainer.
- **Request**:

```json
{
  "education_type": "course_or_certificate",
  "institution_name": "Skillbox",
  "program_or_title": "Фитнес-нутрициология",
  "degree_level": null,
  "country": "Беларусь",
  "city": "Минск",
  "start_year": 2023,
  "end_year": 2024,
  "is_in_progress": false,
  "document_url": "https://example.com/cert.pdf"
}
```

- **Validation**:
  - required: `education_type`, `institution_name`, `program_or_title`
  - reject empty/whitespace strings
  - `start_year <= end_year` when both are provided
- **Response 201**:

```json
{
  "id": "uuid",
  "moderation_status": "pending_moderation"
}
```

### PATCH `/api/trainers/{trainer_id}/education/{education_id}`

- **Purpose**: Trainer edits an existing record.
- **Behavior**:
  - if target is `approved`, create a pending revision (new row) and preserve public approved snapshot;
  - if target is `pending_moderation`/`rejected`, update in place and keep status `pending_moderation`.
- **Response 200**:

```json
{
  "id": "uuid",
  "moderation_status": "pending_moderation",
  "revision_created": true
}
```

### GET `/api/public/trainers/{trainer_id}/education`

- **Purpose**: Public profile data for clients.
- **Rule**: return `approved` records only.

## 2) Admin Moderation Contract (via full profile card)

### POST `/api/admin/trainers/{trainer_id}/profile-moderation-decision`

- **Request**:

```json
{
  "decision": "rejected",
  "reason": "Нужна более точная формулировка программы обучения",
  "affected_sections": ["education"]
}
```

- **Rules**:
  - `decision in [approved, rejected]`
  - `reason` required when `decision = rejected`
  - decision applies in context of full trainer profile moderation request
  - for `affected_sections` containing `education`, write moderation event rows atomically with education status updates

## 3) Telegram bot interaction contract

### Trainer bot flow

1. Trainer opens profile -> taps "Образование".
2. Bot asks 3 required inputs in short guided sequence:
   - тип образования,
   - учреждение,
   - программа/название.
3. Bot optionally asks for details ("добавить годы/город/ссылку?"), with "Пропустить".
4. Bot confirms save and status: "На модерации".

### Admin bot moderation card (single full profile card)

- Card includes:
  - trainer id/name
  - key profile fields (город, услуги, описание и другие текущие поля профиля)
  - education type
  - institution + program
  - optional fields if provided
  - inline buttons: `Одобрить`, `Отклонить`
- For reject:
  - admin enters mandatory reason
  - system updates status and sends trainer notification

### Notifications

- On approve: short success message + display hint where record is visible.
- On reject: reason + CTA "Исправить запись" (deep link/callback).
