-- One-off cleanup: remove catalog rows named by tests (Test Service, E2E Service).
-- Run against staging/dev only after backup. Adjust "keeper" logic if needed.
--
-- Why DELETE alone fails: bookings.service_id references services ON DELETE RESTRICT.
--
-- Steps: reassign bookings → drop dependent rows → delete junk service ids.

BEGIN;

-- Preview (run separately if you want to inspect)
-- SELECT id, name FROM services WHERE name IN ('Test Service', 'E2E Service');

-- Canonical service to attach orphaned bookings (first real catalog row — NOT test names)
WITH keeper AS (
  SELECT id AS keeper_id
  FROM services
  WHERE name NOT IN ('Test Service', 'E2E Service')
  ORDER BY id
  LIMIT 1
),
junk AS (
  SELECT id AS junk_id
  FROM services
  WHERE name IN ('Test Service', 'E2E Service')
)
UPDATE bookings b
SET service_id = (SELECT keeper_id FROM keeper)
WHERE b.service_id IN (SELECT junk_id FROM junk);

-- trainer_services: CASCADE on delete would run after parent delete; clear explicitly if needed
DELETE FROM trainer_services
WHERE service_id IN (SELECT id FROM services WHERE name IN ('Test Service', 'E2E Service'));

-- client_requests reference services with CASCADE — delete junk-linked requests or reassign first
DELETE FROM client_requests
WHERE service_id IN (SELECT id FROM services WHERE name IN ('Test Service', 'E2E Service'));

-- pass products: FK SET NULL on delete
UPDATE trainer_pass_products
SET service_id = NULL
WHERE service_id IN (SELECT id FROM services WHERE name IN ('Test Service', 'E2E Service'));

-- client_sessions may point at selected_service_id
UPDATE client_sessions
SET selected_service_id = NULL
WHERE selected_service_id IN (SELECT id FROM services WHERE name IN ('Test Service', 'E2E Service'));

DELETE FROM services
WHERE name IN ('Test Service', 'E2E Service');

COMMIT;
