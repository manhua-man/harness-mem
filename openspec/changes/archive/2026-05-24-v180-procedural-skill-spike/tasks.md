## 1. Candidate shape

- [x] 1.1 Define a procedural candidate schema for ordered workflows
- [x] 1.2 Preserve provenance and review status fields
- [x] 1.3 Keep the schema read-only for the spike
- [x] 1.4 Define confirmed `Skill` schema with usage and success-rate counters
- [x] 1.5 Persist procedural candidates and confirmed skills in dedicated structured namespaces

## 2. Fixture set

- [x] 2.1 Add a small fixture for a repeated focused-test loop
- [x] 2.2 Add a small fixture for a review-and-merge loop
- [x] 2.3 Add a small fixture for a maintenance loop

## 3. Validation

- [x] 3.1 Verify fixture parsing stays within read-only boundaries
- [x] 3.2 Confirm the spike does not touch wake selection or truth mutation
- [x] 3.3 Record the procedural boundary in the next roadmap update
- [x] 3.4 Verify confirm -> search_skills -> record_skill_result flow through storage, CLI, and MCP
- [x] 3.5 Confirm procedural skills stay out of default wake selection
