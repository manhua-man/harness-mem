# v299-reflection-project-root-resolution

OpenSpec change for harness-mem v2.9.9.

Theme: make `reflection_once(project_root=None)` prefer a known project root
before falling back to the caller's current working directory.
