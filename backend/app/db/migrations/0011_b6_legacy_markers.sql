-- B6: rows stored before observation tracking and GDACS match status existed.
-- Not inferred from other columns: their state is simply unknown.
UPDATE events SET observation_state = 'unknown_legacy' WHERE observation_state IS NULL;
UPDATE events SET gdacs_match_status = 'not_checked' WHERE gdacs_match_status IS NULL;
