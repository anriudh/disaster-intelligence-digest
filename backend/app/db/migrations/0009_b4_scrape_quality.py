"""
B4: label the extraction quality of rows stored before A4. Text is kept as is;
rows whose text is a JavaScript-shell message are marked rejected_boilerplate.
"""
VERSION = 9

# Exact texts seen in stored rows (fixed here so this migration never changes)
SHELL_TEXTS = (
    "You need to enable JavaScript to run this app.",
)


def migrate(conn):
    placeholders = ", ".join("?" for _ in SHELL_TEXTS)
    conn.execute(
        f"UPDATE event_analysis SET scrape_quality = 'rejected_boilerplate' "
        f"WHERE scrape_quality IS NULL AND TRIM(raw_text) IN ({placeholders})",
        SHELL_TEXTS,
    )
    conn.execute("UPDATE event_analysis SET scrape_quality = 'legacy_unchecked' WHERE scrape_quality IS NULL")
