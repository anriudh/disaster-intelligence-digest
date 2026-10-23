-- Where event_analysis.raw_text came from: a source URL, or "fallback" (title and description)
ALTER TABLE event_analysis ADD COLUMN scrape_source TEXT;
-- extracted / fallback / rejected_boilerplate / legacy_unchecked
ALTER TABLE event_analysis ADD COLUMN scrape_quality TEXT;
