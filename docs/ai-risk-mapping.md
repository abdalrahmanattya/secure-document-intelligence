# AI risk mapping

The controls follow NIST AI RMF's Govern, Map, Measure, and Manage functions. Govern: owners, audit events, model adapter configuration, and human approval are documented. Map: documents are untrusted inputs, extraction is bounded to an explicit schema, and low confidence is routed to review. Measure: fixtures cover clean extraction, injection, malware, malformed input, confidence, and correction. Manage: failed or uncertain jobs go to review/DLQ, outputs include citations, and model output never executes tools or changes data without a reviewer.
