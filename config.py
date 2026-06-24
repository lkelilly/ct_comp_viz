"""
config.py
─────────
Shared constants used across all files.
"""

# ── Trial Information table ───────────────────────────────────────────────────

# Readable column headers for the Trial Information table
# Maps DataFrame column name to display label
TRIAL_TABLE_LABELS = {
    "nct_number":                 "NCT Number",
    "relevant_publication":       "Relevant Publication",
    "publication_source":         "Publication Source",
    "acronym":                    "Acronym",
    "study_title":                "Study Title",
    "indication":                 "Indication",
    "compound":                   "Compound",
    "conditions":                 "Conditions",
    "interventions":              "Interventions",
    "enrollment":                 "Enrollment",
    "start_date":                 "Start Date",
    "primary_completion_date":    "Primary Completion",
    "completion_date":            "Completion Date",
    "phases":                     "Phase",
    "study_status":               "Status",
    "study_type":                 "Study Type",
    "study_results":              "Results",
    "brief_summary":              "Brief Summary",
    "primary_outcome_measures":          "Primary Outcome Measures",
    "secondary_outcome_measures":        "Secondary Outcome Measures",
    "simplified_primary_outcome":        "Simplified Primary Outcome",
    "simplified_secondary_outcome":      "Simplified Secondary Outcome",
    "inclusion_criteria":                "Inclusion Criteria",
    "exclusion_criteria":                "Exclusion Criteria",
    "sponsor":                    "Sponsor",
    "funder_type":                "Funder Type",
}

# Columns where text should be truncated in the table (long free-text fields)

## future feature? simplified the texts stuff
## now it just cuts off anything that's more than 200 words
TRUNCATE_COLS = [
    "brief_summary",
    "primary_outcome_measures",
    "secondary_outcome_measures",
    "simplified_primary_outcome",
    "simplified_secondary_outcome",
    "conditions",
    "interventions",
    "inclusion_criteria",
    "exclusion_criteria",
]

TRUNCATE_LENGTH = 200   # matching old version for now, need to change