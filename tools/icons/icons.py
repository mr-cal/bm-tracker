"""The geometry for every achievement icon.

Pure data. `source.py` owns the wrapper; this owns the drawings.

Each drawing is a small joke. Some are literal — Hard as Nails is a nail, The
Full Night Out is a night sky. Some are the opposite — a dice face for a
streak, a bell for a Bristol 7. The rule was that it has to be *legible at 40
pixels first and funny second*, because a collection page is something you scan
rather than read, and an icon you have to squint at is not a joke.
"""

from __future__ import annotations

ICONS: dict[str, str] = {
    # --- the first ones ---------------------------------------------------
    "first_blood": '<path d="M12 3c3.4 4.1 5.5 6.8 5.5 9.3a5.5 5.5 0 0 1-11 0C6.5 9.8 8.6 7.1 12 3Z"/>'
    '<path d="M9.8 12.6a2.4 2.4 0 0 0 2.2 2.4"/>',
    "night_owl": '<path d="M5 5.5 6.5 9M19 5.5 17.5 9"/><circle cx="12" cy="13" r="7"/>'
    '<circle cx="9.4" cy="12" r="1.4"/><circle cx="14.6" cy="12" r="1.4"/>'
    '<path d="m12 15.4-1.3 1.8h2.6Z"/>',
    # A sunrise, not a bird. Every bird drawn at 24px with a 1.7 stroke came out
    # as a squiggle, and a squiggle does not survive being 40 pixels tall.
    "early_bird": '<path d="M2.5 18.5h19"/><path d="M6.5 18.5a5.5 5.5 0 0 1 11 0"/>'
    '<path d="M12 8.5V5.5M4.6 10.8 2.8 9M19.4 10.8 21.2 9"/>',
    # --- Bristol, one at a time -------------------------------------------
    "type_7": '<path d="M6.5 17.5c0-5.4 1.2-8.5 5.5-8.5s5.5 3.1 5.5 8.5Z"/>'
    '<path d="M4.5 17.5h15"/><path d="M12 6.8V5.4"/><circle cx="12" cy="3.9" r="1.1"/>',
    "type_1": '<path d="M4 6.5h16"/><path d="M12 6.5v8.5"/><path d="m12 15-3 4.5h6Z"/>',
    "gold_star": '<path d="m12 3.6 2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4-3.9-3.8 5.4-.8Z"/>'
    '<path d="M17.5 3v3M16 4.5h3"/>',
    # A goblet. The obvious drawing is a monocle, and a monocle at this size is
    # a magnifying glass, which is what Undocumented already is.
    "connoisseur": '<path d="M7.5 4h9l-1.2 6.4a3.3 3.3 0 0 1-6.6 0Z"/>'
    '<path d="M12 13.8V18"/><path d="M8.5 20.5h7"/><path d="M8.6 8.4c2 .9 4.8.9 6.8 0"/>',
    "type_one": '<path d="M4 6.5h16"/><path d="M12 6.5v8.5"/><path d="m12 15-3 4.5h6Z"/>'
    '<circle cx="19" cy="19" r="2.6"/>',
    # --- how many in a day ------------------------------------------------
    "the_double": '<circle cx="7.5" cy="12" r="3.6"/><circle cx="16.5" cy="12" r="3.6"/>'
    '<path d="M4 20h16"/>',
    "triple_threat": '<circle cx="12" cy="6" r="2.9"/><circle cx="6.4" cy="15.6" r="2.9"/>'
    '<circle cx="17.6" cy="15.6" r="2.9"/>',
    "marathon": '<path d="M6 21V3.5"/><path d="M6 4.5h12l-3 3.6 3 3.6H6"/>'
    '<path d="M3 21h6"/>',
    # A megaphone rather than a mouth. Ten in a day deserves a loudspeaker, and
    # a mouth drawn as an ellipse with lines round it is just a sun.
    "blatherer": '<path d="M3.5 10v4h3.2L14 18.5v-13L6.7 10Z"/>'
    '<path d="M17 9.6a4 4 0 0 1 0 4.8"/><path d="M19.8 6.8a7.8 7.8 0 0 1 0 10.4"/>',
    "four_in_a_day": '<circle cx="6" cy="6" r="2.3"/><circle cx="12" cy="6" r="2.3"/>'
    '<circle cx="18" cy="6" r="2.3"/><circle cx="9" cy="13.5" r="2.3"/>'
    '<circle cx="15" cy="13.5" r="2.3"/><path d="M12 17.5v3M4 20.5h16"/>',
    "seven_in_a_day": '<circle cx="6" cy="6" r="2.2"/><circle cx="12" cy="6" r="2.2"/>'
    '<circle cx="18" cy="6" r="2.2"/><circle cx="6" cy="12" r="2.2"/>'
    '<circle cx="12" cy="12" r="2.2"/><circle cx="18" cy="12" r="2.2"/>'
    '<circle cx="12" cy="18" r="2.2"/><path d="M3 20.5h18"/>',
    # --- writing things down ---------------------------------------------
    "note_to_self": '<path d="M5 3.5h9l5 5v12H5Z"/><path d="M14 3.5v5h5"/>'
    '<path d="M8 12.5h8M8 16h5"/>',
    "lore_master": '<path d="M12 6.4C10 4.9 7.4 4.4 4 4.9v13c3.4-.5 6 .1 8 1.7 2-1.6 4.6-2.2 8-1.7v-13c-3.4-.5-6 0-8 1.5Z"/>'
    '<path d="M12 6.4v13.2"/><path d="M6.6 9.4c1.6-.1 2.8.1 3.8.6M6.6 13c1.6-.1 2.8.1 3.8.6"/>',
    "ghost_writer": '<path d="M6 20.5V10a6 6 0 0 1 12 0v10.5l-2-1.6-2 1.6-2-1.6-2 1.6-2-1.6Z"/>'
    '<circle cx="9.8" cy="10.4" r=".95"/><circle cx="14.2" cy="10.4" r=".95"/>'
    '<path d="M10.4 14.6a2.2 2.2 0 0 0 3.2 0"/>',
    "twelvenotes": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/>'
    '<circle cx="7.2" cy="8.6" r=".9"/><circle cx="12" cy="8.6" r=".9"/>'
    '<circle cx="16.8" cy="8.6" r=".9"/><circle cx="7.2" cy="12" r=".9"/>'
    '<circle cx="12" cy="12" r=".9"/><circle cx="16.8" cy="12" r=".9"/>'
    '<circle cx="7.2" cy="15.4" r=".9"/><circle cx="12" cy="15.4" r=".9"/>'
    '<circle cx="16.8" cy="15.4" r="1.4"/>',
    "ten_notes": '<path d="M7 3.5h10v17l-5-2.6-5 2.6Z"/><path d="M9.5 8h5M9.5 11.5h5"/>',
    "twenty_five_notes": '<path d="M6 3.5h9v17l-4.5-2.4-4.5 2.4Z"/>'
    '<path d="M14 8h4.5v12.5L16 19l-2 1.5"/>'
    '<path d="M8.4 8h3.2M8.4 11.4h3.2"/>',
    "hundred_notes": '<path d="M3 4h5v16l-2.5-1.6L3 20Z"/><path d="M9.5 4h5v16L12 18.4 9.5 20Z"/>'
    '<path d="M16 4h5v16l-2.5-1.6L16 20Z"/>',
    "december_double": '<path d="M5 3.5h9l5 5v12H5Z"/><path d="M14 3.5v5h5"/>'
    '<path d="M8 17.5c1.5-2.6 2.6-2.6 4 0s2.5 2.6 4 0"/>',
    "undocumented": '<path d="M6 3.5h9l4 4v13H6Z"/><path d="M15 3.5v4h4"/>'
    '<circle cx="12" cy="14" r="3.2"/><path d="m10.2 16.2 4 4"/>'
    '<path d="M12 12.6v1.8M12 15.8h.01"/>',
    # A spectrum, not a starburst. Radiating lines from a centre is a star with
    # the corners taken off, and Gold Star is already one of those.
    "one_of_everything": '<path d="M2.5 20.5h19"/><path d="M2.5 20.5 21.5 4"/>'
    '<path d="m5.6 16.4 2 2M9.4 12 12 14.4M13.4 7.6 16 10.2M17.2 3.4 19.8 6"/>',

    # --- speed and streaks ------------------------------------------------
    "speed_run": '<circle cx="12" cy="14" r="6.5"/><path d="M12 10.6V14l2.4 1.4"/>'
    '<path d="M9.5 3.5h5"/><path d="M12 3.5v4"/><path d="m18.4 6.6 1.6-1.6"/>',
    "quick_variety": '<circle cx="12" cy="12" r="8.6"/><circle cx="12" cy="12" r="2.4"/>'
    '<path d="M12 5.4v4.2M18.6 8.7l-3.6 2.1M18.6 15.3l-3.6-2.1M12 18.6v-4.2M5.4 15.3 9 13.2M5.4 8.7 9 10.8"/>',
    "spicy_quick": '<path d="M11 21c-2.6 0-4.4-2.2-4.4-5.4 0-3.4 2.3-6.5 4.4-8.4 2.1 1.9 4.4 5 4.4 8.4 0 3.2-1.8 5.4-4.4 5.4Z"/>'
    '<path d="M11 7.2c0-1.6 1.1-2.6 2.6-2.6"/><path d="m17.4 3.4 2.2-1.2M20.4 6.6l1.4-2M3.4 8l-1.2-2.2"/>',
    "spicy_baby": '<path d="M12 20c-2.2 0-3.8-1.9-3.8-4.6 0-2.9 2-5.6 3.8-7.2 1.8 1.6 3.8 4.3 3.8 7.2 0 2.7-1.6 4.6-3.8 4.6Z"/>'
    '<path d="M12 8.2c0-1.4 1-2.2 2.2-2.2"/><circle cx="18.5" cy="6" r="1.3"/>'
    '<circle cx="5.5" cy="6" r="1.3"/>',
    "spicy_ten": '<path d="M9.5 20.5c-2 0-3.5-1.7-3.5-4.2 0-2.7 1.8-5 3.5-6.4 1.7 1.4 3.5 3.7 3.5 6.4 0 2.5-1.5 4.2-3.5 4.2Z"/>'
    '<path d="M17 20.5c-1.4 0-2.4-1.2-2.4-2.9 0-1.9 1.2-3.5 2.4-4.4 1.2.9 2.4 2.5 2.4 4.4 0 1.7-1 2.9-2.4 2.9Z"/>'
    '<path d="M9.5 10c0-1.2.9-2 2-2"/>',
    "spicy_fifty": '<path d="M4 20.5h16"/><path d="M7 20.5V9l3-3 3 3v11.5"/><path d="M15 20.5v-8l3-2.5 2.5 2.5v8"/>'
    '<path d="M9.5 12.5h1M9.5 16h1M17.5 15.5h.6"/>',

    "spicy_and_urgent": '<path d="M6 3.5h9l4 4v13H6Z"/><path d="M15 3.5v4h4"/>'
    '<path d="M9 12.5c1.4-2.2 2.4-2.2 3.8 0"/><path d="M9 16.5h1.5M14 16.5h1.5"/>'
    '<path d="M16.5 8.4c.9 0 1.6.8 1.6 1.7 0 .8-.4 1.2-1 1.7"/>',
    "spicy_urgent_night": '<path d="M16.5 18.8A7.5 7.5 0 0 1 8 7a7.6 7.6 0 1 0 8.5 11.8Z"/>'
    '<circle cx="17.5" cy="6" r=".9"/><circle cx="20.5" cy="9.5" r=".9"/>'
    '<path d="M11 13.5c0-1.4 1-2.3 2.3-2.3"/>',
    "spicy_type_seven": '<path d="M6.5 17.5c0-5.4 1.2-8.5 5.5-8.5s5.5 3.1 5.5 8.5Z"/><path d="M4.5 17.5h15"/>'
    '<path d="M12 6.8V5.4"/><path d="m18.5 3.5 2 4h-4Z"/>',
    "spicy_comeback": '<path d="M4.5 11.5a7.5 7.5 0 0 1 12.8-5.3"/><path d="M17.5 2.8v3.6h-3.6"/>'
    '<path d="M19.5 12.5a7.5 7.5 0 0 1-12.8 5.3"/><path d="M6.5 21.2v-3.6h3.6"/>',
    "spicy_streak": '<path d="M3 20.5h18"/><path d="M6.5 20.5v-6l3-2.5 3 2.5v6"/><path d="M15 20.5v-6l2.5-2 2.5 2v6"/>'
    '<path d="m9 4.5 1.5 3 3 .4-2.2 2.1.6 3-2.9-1.5-2.9 1.5.6-3L4.5 7.9l3-.4Z"/>',
    "fiery_streak": '<path d="M3.5 20.5h17"/><path d="M6.5 20.5 9 9.5h6l2.5 11"/>'
    '<path d="M8.5 9.5c0-2.2 1.6-3.6 3.5-3.6s3.5 1.4 3.5 3.6"/>'
    '<path d="M10 4c.4-1 1.3-1.5 2-1.5s1.6.5 2 1.5"/>',
    "dawn_spicy": '<path d="M13 21c-2.2 0-3.8-1.9-3.8-4.6 0-2.9 2-5.6 3.8-7.2 1.8 1.6 3.8 4.3 3.8 7.2 0 2.7-1.6 4.6-3.8 4.6Z"/>'
    '<path d="M13 9.2c0-1.4 1-2.2 2.2-2.2"/><path d="M4.5 3.5v3M3 5h3M6 3.4 7.4 2M7.4 3.4 6 2"/>',
    # --- streaks ----------------------------------------------------------
    "perfect_week": '<circle cx="3.2" cy="12" r="1.1"/><circle cx="6.5" cy="12" r="1.1"/>'
    '<circle cx="9.8" cy="12" r="1.1"/><circle cx="13.2" cy="12" r="1.1"/>'
    '<circle cx="16.5" cy="12" r="1.1"/><circle cx="19.8" cy="12" r="1.1"/>'
    '<path d="M20.6 4.5a4 4 0 0 1 0 5"/><path d="M20.6 14.5a4 4 0 0 1 0 5"/>',
    "fortnight": '<circle cx="4" cy="8" r="1.1"/><circle cx="7.4" cy="8" r="1.1"/>'
    '<circle cx="10.8" cy="8" r="1.1"/><circle cx="14.2" cy="8" r="1.1"/>'
    '<circle cx="17.6" cy="8" r="1.1"/><circle cx="21" cy="8" r="1.1"/>'
    '<circle cx="4" cy="13" r="1.1"/><circle cx="7.4" cy="13" r="1.1"/>'
    '<circle cx="10.8" cy="13" r="1.1"/><circle cx="14.2" cy="13" r="1.1"/>'
    '<circle cx="17.6" cy="13" r="1.1"/><circle cx="21" cy="13" r="1.1"/>'
    '<path d="M2 18.5h20"/>',
    "unbroken": '<rect x="2.5" y="8.5" width="8.5" height="7" rx="3.5"/>'
    '<rect x="13" y="8.5" width="8.5" height="7" rx="3.5"/>',
    "weekend_streak": '<path d="M2.5 20.5h19"/><path d="M4 17V9.5M8 17V9.5M12 17V9.5M16 17V9.5M20 17V9.5"/>'
    '<path d="M15 6.5h5v3h-5Z"/><path d="m2 6.5 2 2M6 6.5 4 8.5"/>',
    "night_streak": '<path d="M17 19.5A8 8 0 0 1 7.5 6.5 8.1 8.1 0 1 0 17 19.5Z"/>'
    '<circle cx="18" cy="4.5" r=".9"/><path d="M5 4.5h4M5 8h3"/>',
    "night_owl_streak": '<circle cx="12" cy="13.5" r="7"/><path d="M5.5 6 7 9.5M18.5 6 17 9.5"/>'
    '<circle cx="9.6" cy="12.5" r="1.3"/><circle cx="14.4" cy="12.5" r="1.3"/>'
    '<path d="M3 4.5h3M18 4.5h3"/>',
    "dawn_patrol": '<path d="M9.5 21V9.5h5V21Z"/><path d="M8 9.5 12 4l4 5.5Z"/>'
    '<path d="M9.5 14h5M9.5 17h5"/><path d="M17 7.5 21.5 6M17 10.5 22 10.5M17 13.5 21.5 15"/>',
    "quick_streak": '<path d="M13 2.5 5.5 13.5H11l-1 8 8-11.5h-5.5Z"/>',
    "note_streak": '<path d="M7 3.5h10v17l-5-2.6-5 2.6Z"/><path d="M2 8h3M2 12h2M2 16h3"/>'
    '<path d="M19 8h3M20 12h2M19 16h3"/>',
    "documented_streak": '<path d="M5.5 3.5h9l4 4v13h-13Z"/><path d="M14.5 3.5v4h4"/>'
    '<path d="M8.5 12h7M8.5 15.5h4.5"/><path d="M2 8.5h2M2 12h1.5M2 15.5h2"/>',
    "noted_run": '<path d="M2.5 19.5h19"/><circle cx="6" cy="14" r="1.6"/>'
    '<circle cx="11" cy="11" r="1.6"/><circle cx="16" cy="8" r="1.6"/>'
    '<path d="m19 4 2 2-3.2 3.2-2-2Z"/>',
    "noted_comeback_streak": '<path d="M4 8.5a8 8 0 0 1 13.6-4"/><path d="M18 2v3.2h-3.2"/>'
    '<path d="M20 15.5a8 8 0 0 1-13.6 4"/><path d="M6 22v-3.2h3.2"/>'
    '<path d="M12 10.5 13.5 13l2.5.3-1.8 1.7.4 2.5-2.1-1.2-2.1 1.2.4-2.5L9 13.3l2.5-.3Z"/>',
    "backfilled_streak": '<path d="M2.5 19.5h19"/><rect x="4" y="12" width="4" height="7.5" rx="1"/>'
    '<rect x="10" y="9" width="4" height="10.5" rx="1"/><rect x="16" y="6" width="4" height="13.5" rx="1"/>'
    '<path d="M4 9.5 20 3.5"/>',

    "quick_and_long": '<circle cx="5" cy="16" r="3"/><path d="M8 16h3"/><path d="M14 4v12"/>'
    '<path d="m11 4 3-2 3 2"/><path d="M18.5 8.5v7.5M15.5 13l3 3 3-3"/>',

    # --- the calendar -----------------------------------------------------
    # Sixteen of these, which is the hardest block in the set. The rule that
    # got them apart: no two share a silhouette, so nothing has to be read to
    # tell them apart.
    "new_years_day": '<circle cx="12" cy="12" r="2.4"/>'
    '<path d="M12 6V2.5M12 21.5V18M6 12H2.5M21.5 12H18M7.8 7.8 5.4 5.4M18.6 18.6l-2.4-2.4M18.6 5.4l-2.4 2.4M7.8 16.2l-2.4 2.4"/>'
    '<path d="M9.5 9.5c1-1.4 4-1.4 5 0M9.5 14.5c1 1.4 4 1.4 5 0"/>',

    "valentines_day": '<path d="M12 20.5S3.5 15.2 3.5 9.6A4.6 4.6 0 0 1 12 7.2a4.6 4.6 0 0 1 8.5 2.4c0 5.6-8.5 10.9-8.5 10.9Z"/>',

    "ides_of_march": '<path d="M12 2.5 9.5 8v6.5h5V8Z"/><path d="M7.5 14.5h9"/>'
    '<path d="M12 17.5v4M10 21.5h4"/>',
    "april_fools": '<path d="M6.5 20.5a5.5 5.5 0 0 1 11 0Z"/><path d="M12 15 9 6.5M12 15l3-8.5M12 15V5"/>'
    '<circle cx="9" cy="5" r="1.2"/><circle cx="15" cy="5" r="1.2"/><circle cx="12" cy="3.6" r="1.2"/>',
    "may_day": '<circle cx="12" cy="9" r="2.4"/><path d="M12 6.6V3.5M12 11.4v2.4"/>'
    '<path d="M9.6 9H6.5M14.4 9h3.1M10.3 7.3 8.1 5.1M13.7 7.3l2.2-2.2M10.3 10.7l-2.2 2.2M13.7 10.7l2.2 2.2"/>'
    '<path d="M12 13.8V21"/>',
    "midsummer": '<circle cx="12" cy="12" r="4.4"/><path d="M12 3.5v2.4M12 18.1v2.4M3.5 12h2.4M18.1 12h2.4"/>'
    '<path d="M6 6 7.7 7.7M16.3 16.3 18 18M18 6l-1.7 1.7M7.7 16.3 6 18"/>',
    "halloween": '<path d="M12 7.5a5.6 5.6 0 0 1 5.3 3.7 5.6 5.6 0 0 1-2.7 9.6 5.6 5.6 0 0 1-5.2 0 5.6 5.6 0 0 1-2.7-9.6A5.6 5.6 0 0 1 12 7.5Z"/>'
    '<path d="M12 7.5V4.5"/><path d="m9.8 11.5-1.4 2M14.2 11.5l1.4 2"/>'
    '<path d="M9.4 16.4c1.6 1.1 3.6 1.1 5.2 0"/>',
    "bonfire_night": '<path d="M4 20.5h16"/><path d="M12 3.5c3 2.6 4.6 5 4.6 7.3a4.6 4.6 0 0 1-9.2 0c0-2.3 1.6-4.7 4.6-7.3Z"/>'
    '<path d="M12 13.5c-1.3 1.2-2 2.3-2 3.2a2 2 0 0 0 4 0c0-.9-.7-2-2-3.2Z"/>'
    '<circle cx="4.5" cy="4.5" r=".9"/><circle cx="19.5" cy="4.5" r=".9"/>',
    "winter_solstice": '<path d="M9 20.5h6"/><path d="M10 20.5v-4h4v4"/>'
    '<path d="M12 16.5v-2.2"/><path d="M12 11.5c1.6 0 2.4 1 2.4 2.4 0 1.1-.8 1.9-2.4 2.4-1.6-.5-2.4-1.3-2.4-2.4 0-1.4.8-2.4 2.4-2.4Z"/>'
    '<path d="M4 8.5l1.6 1.6M20 8.5l-1.6 1.6M3 14h2M19 14h2"/>',
    "christmas_eve": '<path d="M8 3.5h8l1.5 4.5H6.5Z"/><path d="M6.5 8h11l-1 13h-9Z"/>'
    '<path d="M9 12.5h6M9 16h4"/>',
    "christmas_day": '<path d="M3.5 9.5h17v11h-17Z"/><path d="M3.5 9.5 5.5 4h13l2 5.5"/>'
    '<path d="M12 9.5v11"/><path d="M12 9.5c-3 0-4-1.4-3.4-2.6.6-1.2 2.4-.6 3.4 2.6Z"/>'
    '<path d="M12 9.5c3 0 4-1.4 3.4-2.6-.6-1.2-2.4-.6-3.4 2.6Z"/>',
    "boxing_day": '<path d="M3 8.5h18v12H3Z"/><path d="M3 8.5 6 4.5h12l3 4"/>'
    '<path d="M12 8.5v12"/><path d="M7 12.5h2.5M14.5 12.5H17M7 16.5h2.5M14.5 16.5H17"/>',

    "new_years_eve": '<circle cx="12" cy="13" r="8"/><path d="M12 8.5V13l3 2"/>'
    '<path d="M12 2.5v3M4 6.5l1.8 1.8M20 6.5l-1.8 1.8"/><path d="M4.5 19.5 2 21M19.5 19.5 22 21"/>',
    "christmas_quick": '<path d="M3.5 9.5h17v11h-17Z"/><path d="M3.5 9.5 5.5 4h13l2 5.5"/><path d="M12 9.5v11"/>'
    '<path d="M17 3.5 14 9M19.5 5 16 9.5"/>',
    "halloween_night": '<path d="M16.5 19A7.5 7.5 0 0 1 8 6.6 7.6 7.6 0 1 0 16.5 19Z"/>'
    '<path d="M12 8.5a4 4 0 0 1 3.4 1.9A3.6 3.6 0 0 0 12 9.6a3.6 3.6 0 0 0-3.4.8A4 4 0 0 1 12 8.5Z"/>'
    '<path d="m9.8 12.2 1 1M14.2 12.2l-1 1"/>',
    "valentine_quick": '<path d="M12 20.5S4 15.4 4 10.2A4.4 4.4 0 0 1 12 8a4.4 4.4 0 0 1 8 2.2c0 5.2-8 10.3-8 10.3Z"/>'
    '<path d="M3 6.5h4M2 10h2.5"/>',
    "new_year_same_day": '<rect x="3" y="4.5" width="18" height="16" rx="2.5"/>'
    '<path d="M3 9h18M8 2.5v4M16 2.5v4"/><circle cx="12" cy="15" r="2.6"/>',

    # --- silence ----------------------------------------------------------

    "wordless_year": '<path d="M3 5h6.5v14L6 17 3 19Z"/><path d="M14.5 5H21v14l-3.5-2-3 2Z"/>'
    '<path d="M6 9.5v0M6 12.5v0M18 9.5v0M18 12.5v0"/>',
    "confession": '<path d="M4 4.5h16v15H4Z"/><path d="M12 4.5v8"/>'
    '<path d="m8 12.5-2 3h4Z"/><path d="M8 18.5h8"/>',
    "time_traveller": '<circle cx="12" cy="13" r="7.5"/><path d="M12 8.5V13l3 1.8"/>'
    '<path d="M4 4.5 8 7.5M8 4.5 4 7.5"/><path d="M12 3v2.5M20.5 8l-2.5 1.4"/>',
    "undo": '<path d="M4 9.5h9a5.5 5.5 0 0 1 0 11H8"/>'
    '<path d="m7.5 5.5-3.5 4 3.5 4"/>',
    "regrets": '<path d="M6 7.5h12l-1 13.5H7Z"/><path d="M9 7.5V5.5a3 3 0 0 1 6 0v2"/>'
    '<path d="m9.5 12 5 5M14.5 12l-5 5"/>',
    "weekend_warrior": '<path d="M4 20.5h16"/><path d="M12 4v16.5"/><path d="M12 7 4 11.5h8Z"/>'
    '<path d="M12 7l8 4.5h-8Z"/><path d="M8.5 3.5h7"/>',
    "weekday_only": '<rect x="3" y="7.5" width="18" height="12" rx="2"/>'
    '<path d="M9 7.5v-2a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><path d="M3 12.5h18"/>'
    '<path d="m15.5 15 2 2 2-2"/>',
    "weekday_sweep": '<path d="M3 6h18"/><path d="M3 6v14M21 6v14"/>'
    '<circle cx="6.5" cy="10" r="1.5"/><circle cx="9.5" cy="10" r="1.5"/>'
    '<circle cx="12.5" cy="10" r="1.5"/><circle cx="15.5" cy="10" r="1.5"/>'
    '<circle cx="18.5" cy="10" r="1.5"/><path d="M3 15h18"/>',
    "working_week": '<rect x="3" y="4.5" width="18" height="16" rx="2"/>'
    '<path d="M3 9h18"/><path d="M7.5 4.5V2.5M16.5 4.5V2.5"/>'
    '<path d="M6 13h3v3H6ZM10.5 13h3v3h-3ZM15 13h3v3h-3Z"/>',
    "annual_review": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.2"/>'
    '<path d="M12 3.5v6M20.5 12h-6M12 20.5v-6M3.5 12h6M18 6l-4.2 4.2M6 18l4.2-4.2"/>',
    "not_a_streak": '<circle cx="5" cy="16" r="2.4"/><circle cx="19" cy="8" r="2.4"/>'
    '<path d="M7.4 14.6 16.6 9.4" stroke-dasharray="1.5 2.5"/>',
    "monotony": '<rect x="3" y="5" width="5" height="5" rx="1"/><rect x="9.5" y="5" width="5" height="5" rx="1"/>'
    '<rect x="16" y="5" width="5" height="5" rx="1"/><rect x="3" y="11.5" width="5" height="5" rx="1"/>'
    '<rect x="9.5" y="11.5" width="5" height="5" rx="1"/><rect x="16" y="11.5" width="5" height="5" rx="1"/>',
    "weekend_none": '<circle cx="12" cy="12" r="8.5"/><path d="M5.5 5.5 18.5 18.5"/>'
    '<path d="M8 10h3M8 13.5h3"/><path d="m14.5 10 1.5 1.5 1.5-1.5"/>',
    "half_and_half": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 0 0 17Z"/>',
    "two_thirds": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17"/><path d="M12 3.5a8.5 8.5 0 0 1 7.4 4.3H12Z"/>',
    "every_third": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17"/>'
    '<path d="M20.5 12A8.5 8.5 0 0 0 12 20.5V12Z"/><path d="M12 3.5A8.5 8.5 0 0 0 4.6 7.7H12Z"/>',
    # --- the small hours --------------------------------------------------
    "after_hours": '<path d="M17 19.5A8 8 0 0 1 7.5 6.5 8.1 8.1 0 1 0 17 19.5Z"/>'
    '<path d="M2.5 12h3M18.5 12h3"/>',
    "early_bird_tier": '<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 1.5"/>'
    '<path d="M7 4.5 4.5 2M17 4.5 19.5 2M3 9.5H1M21 9.5h2"/>',

    "dawn_ten": '<path d="M2.5 19.5h19"/><path d="M6.5 19.5a5.5 5.5 0 0 1 11 0"/>'
    '<path d="M12 8.5V4.5M12 4.5 9.5 2M12 4.5 14.5 2"/>',
    # --- totals -----------------------------------------------------------
    "century": '<path d="M5 20.5V9M5 9l4-4M5 9l4 4"/><path d="M9 9h4v11.5H9"/>'
    '<path d="M17 9h4v11.5h-4Z"/>',
    "two_hundred": '<path d="M3.5 20.5V8.5l4-3.5 4 3.5v12"/><path d="M13.5 20.5v-9l4-3 3 3v9"/>'
    '<path d="M2 4.5h4M2 4.5l3 2"/>',
    "five_hundred": '<path d="M3 20.5h18"/><path d="M6 20.5v-8l3-2.5 3 2.5v8"/>'
    '<path d="M14 20.5v-8l3-2.5 3 2.5v8"/><path d="M12 3.5v3M12 6.5l-2 2M12 6.5l2 2"/>',
    "thousand": '<path d="M3.5 20.5 12 3.5l8.5 17Z"/><path d="M7 14h10"/><circle cx="12" cy="10" r="1"/>',
    "long_and_annotated": '<path d="M4 20.5h16"/><rect x="3" y="6" width="4" height="12" rx="1"/>'
    '<rect x="8" y="3" width="4" height="15" rx="1"/><rect x="13" y="8" width="4" height="10" rx="1"/>'
    '<rect x="18" y="5" width="4" height="13" rx="1"/>',

    "strain_hard": '<path d="M4 9.5h16"/><path d="M12 9.5v4"/><path d="m12 13.5-3.5 4.5h7Z"/>'
    '<path d="M6 20.5 18 4" stroke-dasharray="1.5 2.5"/>',
    # --- time, counted ----------------------------------------------------
    "fifty_days": '<path d="M2.5 19.5h19"/><circle cx="6" cy="14" r="1.6"/><circle cx="10" cy="14" r="1.6"/>'
    '<circle cx="14" cy="14" r="1.6"/><circle cx="18" cy="14" r="1.6"/><circle cx="21" cy="9" r="1.6"/>'
    '<circle cx="5" cy="9" r="1.6"/>',
    "hundred_days": '<path d="M3 19.5h18"/><rect x="3.5" y="13" width="3.5" height="6.5" rx="1"/>'
    '<rect x="8" y="9" width="3.5" height="10.5" rx="1"/><rect x="12.5" y="5" width="3.5" height="14.5" rx="1"/>'
    '<rect x="17" y="11" width="3.5" height="8.5" rx="1"/>',
    "a_year_of_days": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17M3.5 12h17"/>'
    '<path d="m12 3.5 8.5 8.5M3.5 12 12 20.5"/><circle cx="12" cy="12" r="1.6"/>',
    "first_week": '<path d="M2.5 19.5h19"/><path d="M4 19.5V9l4-3.5 4 3.5v10.5"/>'
    '<path d="M14 19.5v-7l3-2.5 3 2.5v7"/><path d="M2 9.5 20 5" stroke-dasharray="1.5 2.5"/>',
    "all_seven_streak": '<path d="M2.5 19.5h19"/><circle cx="5" cy="14" r="1.8"/><circle cx="8.8" cy="14" r="1.8"/>'
    '<circle cx="12" cy="14" r="1.8"/><circle cx="15.2" cy="14" r="1.8"/><circle cx="19" cy="14" r="1.8"/>'
    '<path d="m5 12.2-1.6-1.6M19 12.2l1.6-1.6M12 12.2V9.4"/>',
    "triple_types": '<circle cx="7" cy="8" r="3"/><circle cx="17" cy="8" r="3"/>'
    '<circle cx="12" cy="16.5" r="3"/><path d="M2.5 20.5h19"/>',
    "weekend_variety": '<path d="M4 20.5h16"/><path d="M12 4v16.5"/><path d="M12 7 4 11.5h8Z"/>'
    '<path d="M12 7l8 4.5h-8Z"/><circle cx="7" cy="15" r="1.3"/><circle cx="12" cy="17" r="1.3"/>'
    '<circle cx="17" cy="15" r="1.3"/>',
    # --- untouched records -----------------------------------------------
    "unmarked": '<path d="M5 3.5h14v17H5Z"/><path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4"/>'
    '<circle cx="12" cy="12" r="11" stroke-dasharray="2 3"/>',
    "untouched": '<path d="M12 3.5 5 6.5v5.5c0 4.4 3 7.4 7 8.5 4-1.1 7-4.1 7-8.5V6.5Z"/>'
    '<path d="m9 12 2.2 2.2L15.5 10"/>',
    # --- returns ----------------------------------------------------------
    "comeback_kid": '<path d="M4 13a8 8 0 0 1 13.7-5.7"/><path d="M18 3v4.5h-4.5"/>'
    '<path d="M20 12.5a8 8 0 0 1-13.7 5.7"/><path d="M6 22v-4.5h4.5"/>',
    "comeback_quick": '<path d="M4 13a8 8 0 0 1 13.7-5.7"/><path d="M18 3v4.5h-4.5"/>'
    '<path d="M12.5 8.5 9 14h3l-1 4.5 4.5-6h-3Z"/>',
    "documented_return": '<path d="M4 13a8 8 0 0 1 13.7-5.7"/><path d="M18 3v4.5h-4.5"/>'
    '<path d="M8.5 15.5h7M8.5 18.5h4"/>',
    "crowded": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17M3.5 12h17"/>'
    '<circle cx="12" cy="8" r="1.3"/><circle cx="16" cy="12" r="1.3"/><circle cx="12" cy="16" r="1.3"/>'
    '<circle cx="8" cy="12" r="1.3"/>',
    "type_seven_streak": '<path d="M6.5 17.5c0-5.4 1.2-8.5 5.5-8.5s5.5 3.1 5.5 8.5Z"/><path d="M4.5 17.5h15"/>'
    '<path d="M12 6.8V5.4"/><path d="M2.5 20.5h19" stroke-dasharray="2 3"/>',
    "the_long_way_round": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 6 14.2"/>'
    '<path d="M12 3.5a8.5 8.5 0 0 0-6 14.2" stroke-dasharray="2 3"/>'
    '<path d="m9 12 2.2 2.2L15.5 10"/>',
    "leap_day": '<ellipse cx="12" cy="13" r="3.1"/><ellipse cx="9.7" cy="5.4" rx="1.15" ry="3.4" transform="rotate(-15 9.7 5.4)"/><ellipse cx="14.3" cy="5.4" rx="1.15" ry="3.4" transform="rotate(15 14.3 5.4)"/><path d="M11 15.5h2"/><path d="M6 20.5h12"/>',
    "groundhog_day": '<path d="M2 18.5a10 10 0 0 1 20 0Z"/><circle cx="12" cy="11.2" r="3.1"/><circle cx="10.85" cy="10.7" r=".7"/><circle cx="13.15" cy="10.7" r=".7"/><path d="M11.2 13.4h1.6"/>',
    "friday_the_thirteenth": '<path d="M5.6 10 5 4.6l4 2.6"/><path d="M18.4 10 19 4.6l-4 2.6"/><path d="M5.6 10a6.4 6.4 0 0 0 12.8 0Z"/><path d="M9.6 12.2h.01M14.4 12.2h.01"/><path d="M12 14.6v1.2M10.4 16.2h3.2"/><path d="M4 21h16"/>',
    "night_ten": '<path d="M2.5 5.5h19v13h-19Z"/><path d="M15.8 14.8a4.4 4.4 0 0 1-5.6-6.5 4.5 4.5 0 1 0 5.6 6.5Z"/><path d="M6.5 8.5h.01M9 11.5h.01M6.5 14.5h.01"/><path d="M2.5 9.5h19"/>',
    "silent_month": '<path d="M3 6h18v12H3Z"/><path d="M6 12h12"/>',
    "silent_streak": '<rect x="2.5" y="5.5" width="19" height="12.5" rx="1.5"/><path d="m2.5 6.5 9.5 6.5 9.5-6.5"/><circle cx="12" cy="14.8" r="2.1"/>',
    "spicy_hundred": '<path d="M6 20.5h12"/><path d="M7.5 20.5v-5.2c-2.1 0-3.6-1.6-3.6-3.7 0-2.2 1.8-3.7 4-3.7.4-1.6 1.9-2.8 4.1-2.8s3.7 1.2 4.1 2.8c2.2 0 4 1.5 4 3.7 0 2.1-1.5 3.7-3.6 3.7v5.2"/>',
    "quick_fifty": '<path d="M3 17.5a9 9 0 0 1 18 0"/><path d="M12 17.5 16.5 8h-3.2l2.2-4.8-5.4 6.4h3.2Z"/>',
    "empty_and_full": '<path d="M6 4.5h12l-1.6 16h-8.8Z"/><path d="M6.7 12.5h10.6"/><circle cx="9" cy="8.5" r="1.15"/><circle cx="15" cy="15.5" r="1.15"/><circle cx="12" cy="17" r="1.15"/>',
}

#: Icons for the note achievements — the ones found by reading a note rather
#: than counting a day.
#:
#: Kept apart from `ICONS` because the two sets are checked against different
#: things: these must not collide with the registry's hundred and twenty, and
#: neither set may collide with itself. Before these existed every note
#: achievement rendered `default.svg`, so a page of thirty-eight identical
#: squares sat underneath a hundred and twenty drawings.
#:
#: The same house rules, and the same discipline about not reusing a silhouette
#: the registry has already spent — no book, no heart, no moon, no megaphone, no
#: sun, so a note achievement never looks like a logging one.
NOTE_ICONS: dict[str, str] = {
    "love_poem": '<path d="M12 20.5S4 15.4 4 10.2A4.4 4.4 0 0 1 12 8a4.4 4.4 0 0 1 8 2.2c0 5.2-8 10.3-8 10.3Z"/>'
    '<path d="M3.5 3.5 6 6M2.5 8h3M6 2.5 4 4.5"/>',
    "poem": '<path d="M4 20.5 15.5 9"/><path d="M13 6.5 17.5 3l3.5 3.5L16.5 10Z"/>'
    '<path d="M4 20.5h4M6.5 14.5 9.5 17.5"/>',
    "nightmare": '<path d="M2.5 18.5h19"/><circle cx="8" cy="10" r="3.4"/>'
    '<path d="M16 6.5c2.5 0 4.5 2 4.5 4.5S18.5 15.5 16 15.5"/>'
    '<path d="M8 7.4c.8-.9 1.6-1.3 2.4-1.3M6 10.6a2.6 2.6 0 0 0 3.6 2.2"/>'
    '<path d="M4 15.5 2.5 18M20 15.5 21.5 18"/>',
    "dream": '<path d="M6 16.5a4 4 0 0 1 .6-8 5 5 0 0 1 9.4 1.4 3.4 3.4 0 0 1-.5 6.6Z"/>'
    '<path d="M10 5.5h3M13 3h3"/>',
    "gratitude": '<path d="M4 13.5a3.5 3.5 0 0 1 3.5-3.5h9A3.5 3.5 0 0 1 20 13.5v1A3.5 3.5 0 0 1 16.5 18h-9A3.5 3.5 0 0 1 4 14.5Z"/>'
    '<path d="M12 12.5s-3-1.8-3-3.6a1.6 1.6 0 0 1 3-.8 1.6 1.6 0 0 1 3 .8c0 1.8-3 3.6-3 3.6Z"/>',
    "anger": '<path d="M12 3.5 13.8 9l5.7-.3-4.4 3.6 1.6 5.5L12 15l-4.7 2.8 1.6-5.5L4.5 8.7 10.2 9Z"/>'
    '<path d="M4 3.5 6 5.5M20 3.5 18 5.5M12 21v-3"/>',
    "grief": '<path d="M6.5 15a4.2 4.2 0 0 1 .6-8.2 5.2 5.2 0 0 1 9.8 1.4 3.6 3.6 0 0 1-.5 6.8Z"/>'
    '<path d="M9 18v2.5M12 18.5v3M15 18v2.5"/>',
    "joy": '<circle cx="12" cy="12" r="5.4"/><path d="M9 10.5c.8 1 1.8 1.5 3 1.5s2.2-.5 3-1.5"/>'
    '<path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4 18 18M18 6l-1.6 1.6M7.6 16.4 6 18"/>',
    "anxiety": '<path d="M5 17.5c2-6 4-6 6 0s4 6 6 0"/><path d="M5 11.5c2-6 4-6 6 0s4 6 6 0"/>'
    '<path d="M4 20.5h16"/>',
    "food_review": '<path d="M6 3v7a2.5 2.5 0 0 0 5 0V3"/><path d="M8.5 10v11"/>'
    '<path d="M16 3c-1.5 2-2 4-2 6.5 0 1.8.8 3 2 3.5V21"/>',
    "poop_review": '<path d="M4 5.5h16v15H4Z"/><path d="M4 9.5h16"/>'
    '<path d="M7 20.5v-7a5 5 0 0 1 10 0v7"/><path d="M10 20.5v-5.5M14 20.5v-5.5"/>',
    "travel": '<path d="M2.5 13.5 21 8l-3 5 3 3-18.5 2.5Z"/><path d="M9 12.5 7 8M15 10.5l-1-3.5"/>',
    "work_rant": '<rect x="3" y="7.5" width="18" height="12" rx="2"/>'
    '<path d="M9 7.5v-2a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><path d="M3 12.5h18"/>'
    '<path d="M15 4.5c1.5 1 1.5 2.5 0 3.5M18 4c2.5 1.5 2.5 4.5 0 6"/>',
    "exams": '<path d="M5 3.5h9l5 5v12H5Z"/><path d="M14 3.5v5h5"/>'
    '<path d="m8.5 14 2 2 4.5-4.5"/>',
    "illness": '<path d="M14 14.8V6a2.5 2.5 0 0 0-5 0v8.8a4 4 0 1 0 5 0Z"/>'
    '<path d="M11.5 8.5v5"/>',
    "weather": '<path d="M6 15a4 4 0 0 1 .6-8 5 5 0 0 1 9.4 1.4 3.4 3.4 0 0 1-.5 6.6Z"/>'
    '<path d="M18 3.5v-1M21 6.5h1M16 3 15 2"/>',
    "sport": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5 15.5 8 12 12 8.5 8Z"/>'
    '<path d="M12 12v8.5M3.5 12h5"/>',
    "family": '<circle cx="8" cy="7" r="2.6"/><circle cx="16" cy="7" r="2.6"/>'
    '<circle cx="12" cy="16" r="2.4"/><path d="M4.5 15c0-2.2 1.6-3.5 3.5-3.5s3.5 1.3 3.5 3.5"/>'
    '<path d="M12.5 15c0-2.2 1.6-3.5 3.5-3.5s3.5 1.3 3.5 3.5"/>',
    "relationship": '<circle cx="9" cy="12" r="5.5"/><circle cx="15" cy="12" r="5.5"/>',
    "breakup": '<circle cx="9" cy="12" r="5.5"/><path d="M15.5 7 9 17"/>'
    '<path d="M4 3.5 6 5M20 3.5 18 5"/>',
    "new_baby": '<path d="M6 9.5a6 6 0 0 1 12 0v4a6 6 0 0 1-12 0Z"/>'
    '<path d="M9 9.5h.01M15 9.5h.01"/><path d="M9.5 16h5"/>'
    '<path d="M12 3.5c1-1.5 2.5-2 3.5-1.5"/>',
    "wedding": '<circle cx="8.5" cy="14.5" r="5"/><circle cx="15.5" cy="14.5" r="5"/>'
    '<path d="m11 5.5 1-3 1 3 3 1-3 1-1 3-1-3-3-1Z"/>',
    "pet": '<ellipse cx="6" cy="9" rx="2" ry="2.6"/><ellipse cx="10.5" cy="6.5" rx="2" ry="2.8"/>'
    '<ellipse cx="15.5" cy="6.5" rx="2" ry="2.8"/><ellipse cx="19.5" cy="9.5" rx="2" ry="2.6"/>'
    '<path d="M12.5 12.5c3 0 5 2.2 5 4.5 0 2-1.6 3.5-3.5 3.5-1 0-1.5-.4-1.5-.4s-.5.4-1.5.4c-1.9 0-3.5-1.5-3.5-3.5 0-2.3 2-4.5 5-4.5Z"/>',
    "garden": '<path d="M12 21v-8"/><path d="M12 13c-3 0-4.5-1.8-4.5-4 2.8 0 4.5 1.5 4.5 4Z"/>'
    '<path d="M12 13c3 0 4.5-1.8 4.5-4-2.8 0-4.5 1.5-4.5 4Z"/><path d="M4 21h16"/>',
    "cooking": '<path d="M3.5 11.5h13v3a4.5 4.5 0 0 1-4.5 4.5H8a4.5 4.5 0 0 1-4.5-4.5Z"/>'
    '<path d="M16.5 13H19a2 2 0 0 1 2 2v3h-4"/><path d="M8 8c0-1.5 1-2 1-3.5M11.5 8c0-1.5 1-2 1-3.5"/>',
    "drink": '<path d="M6 6h12l-1.4 13.5a1.5 1.5 0 0 1-1.5 1.4H8.9a1.5 1.5 0 0 1-1.5-1.4Z"/>'
    '<path d="M6.8 11h10.4"/><path d="M13 2.5 11.5 6M17 2.5 15.5 6"/>',
    "music": '<circle cx="7" cy="17.5" r="3"/><circle cx="18" cy="15.5" r="3"/>'
    '<path d="M10 17.5V6l11-2.5v12"/><path d="M10 9.5 21 7"/>',
    "film": '<path d="M3 7h18v11H3Z"/><path d="M3 7l1.5-3.5h15L21 7"/>'
    '<path d="m7 7 3 2.5L7 12M12 7l3 2.5L12 12M17 7l2.5 2.5L17 12"/>',
    "reading": '<circle cx="6.5" cy="13.5" r="4"/><circle cx="17.5" cy="13.5" r="4"/>'
    '<path d="M10.5 13.5h3M6.5 9.5V7M17.5 9.5V7"/>',
    "money": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v10"/>'
    '<path d="M14.5 9.5c0-1-1.1-1.8-2.5-1.8s-2.5.8-2.5 1.8c0 2.6 5 1.4 5 4 0 1-1.1 1.8-2.5 1.8S9.5 14.5 9.5 13.5"/>',
    "commute": '<rect x="5" y="3.5" width="14" height="14" rx="3"/>'
    '<path d="M5 11.5h14"/><circle cx="9" cy="20.5" r="1.5"/><circle cx="15" cy="20.5" r="1.5"/>'
    '<path d="M9 7.5h6"/>',
    "nature": '<path d="M12 21v-7"/><path d="M12 14a5 5 0 0 0 0-10 5 5 0 0 0 0 10Z"/>'
    '<path d="M12 17.5 8 20M12 17.5l4 2.5"/>',
    "night": '<path d="M3 6.5h5M3 11h3M3 15.5h5"/><circle cx="16" cy="15.5" r="1.2"/>'
    '<circle cx="19.5" cy="19" r="1.2"/><circle cx="19" cy="11.5" r="1.2"/>',
    "first_word": '<path d="M3 5.5h18v11H13l-4 4v-4H3Z"/>'
    '<path d="M8 11h8"/>',
    "one_word": '<path d="M3 5.5h18v11H13l-4 4v-4H3Z"/><circle cx="12" cy="11" r="1.4"/>',
    "all_caps": '<path d="M3 5.5h18v11H13l-4 4v-4H3Z"/>'
    '<path d="M8 13V8.5h2.5M8 10.7h2.2M13 13V8.5h2.2"/>',
    "question": '<path d="M3 5.5h18v11H13l-4 4v-4H3Z"/>'
    '<path d="M10 9.5a2 2 0 0 1 3.9.6c0 1.3-2 1.4-2 2.9"/><path d="M11.9 14.6h.01"/>',
    "exclamation": '<path d="M3 5.5h18v11H13l-4 4v-4H3Z"/><path d="M12 8v3.4"/>'
    '<path d="M12 13.2h.01"/>',
}
