## 1. Renderer

- [x] 1.1 Add a compact wake payload loader for generated wiki bridge artifacts.
- [x] 1.2 Add a compact text renderer that labels output as generated summary.
- [x] 1.3 Preserve source ids in compact output.

## 2. MCP surface

- [x] 2.1 Add opt-in `renderer="compact"` to MCP `wake`.
- [x] 2.2 Keep default `wake` behavior unchanged.
- [x] 2.3 Return a clear error when compact artifacts are missing.

## 3. Validation

- [x] 3.1 Add focused generated-cache compact renderer tests.
- [x] 3.2 Add focused MCP compact wake tests.
- [x] 3.3 Verify generated compact material remains outside default `search_memory`.
