## 1. Candidate model

- [x] 1.1 Add a reviewed `skill_revision_suggestion` candidate type.
- [x] 1.2 Persist skill metrics and recent success/failure signal ids on the candidate.

## 2. Detector

- [x] 2.1 Add a detector for low-success skills using the replay-window thresholds.
- [x] 2.2 Detector creates pending candidates without mutating confirmed skills.
- [x] 2.3 Prevent duplicate pending suggestions from repeated detector runs.

## 3. Review surface

- [x] 3.1 Expose revision suggestions through `list_candidates`.
- [x] 3.2 Add confirm/reject tools that only change candidate status, not the skill body.
- [x] 3.3 Add explicit deprecation suggestions for stale/conflicting shared skills.

## 4. Validation

- [x] 4.1 Add SQLite/store tests for the new candidate type.
- [x] 4.2 Add MCP detector/review tests.
- [x] 4.3 Add focused tests for duplicate suppression and deprecation flow.
