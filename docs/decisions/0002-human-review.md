# ADR 0002: human approval for uncertain output

Extraction confidence below 0.8 and instruction-like content enter `NEEDS_REVIEW`. The model cannot approve, delete, execute, or call tools. Corrections are written as an audit event.
