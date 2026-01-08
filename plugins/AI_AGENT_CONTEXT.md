# AI Agent Context Document for icloudpd

**Purpose**: This document provides comprehensive context for AI coding agents working on the icloudpd project. It is optimized for machine parsing and includes all critical information needed to make informed decisions without re-parsing the entire codebase.

**Last Updated**: 2026-01-02

---

## Project Overview

**Project**: icloudpd - iCloud Photos Downloader
**Language**: Python 3
**Primary Purpose**: Download photos and videos from iCloud Photos Library
**Architecture**: CLI application with plugin system for extensibility

---

## Repository Structure

```
/
├── src/
│   ├── icloudpd/          # Main application code
│   │   ├── base.py        # Core download orchestration (CRITICAL FILE)
│   │   ├── cli.py         # CLI argument parsing
│   │   ├── config.py      # Configuration management
│   │   └── plugins/       # Plugin infrastructure
│   │       ├── base.py    # Base plugin class
│   │       ├── hooks.py   # Hook protocol definitions
│   │       ├── manager.py # Plugin manager
│   │       └── demo.py    # Demo plugin (reference implementation)
│   └── pyicloud_ipd/      # iCloud API wrapper library
│       ├── asset_version.py  # Version/size handling
│       └── utils.py          # Utility functions
├── plugins/               # Bundled plugins (separate from core)
│   └── immich/           # Immich integration plugin
│       ├── immich.py     # Main plugin implementation (1672 lines)
│       ├── README.md     # Plugin documentation
│       └── tests/        # Plugin-specific tests
├── tests/                # Test suite
│   ├── test_plugins.py   # Plugin system tests
│   ├── test_*.py         # Other test files
│   └── helpers/          # Test helper utilities
├── docs/                 # Documentation
│   └── plugins.md        # Plugin development guide (IMPORTANT)
├── scripts/              # Development scripts
│   ├── test              # Run test suite with coverage
│   ├── format            # Format code (ruff format)
│   └── lint              # Lint code (ruff check)
├── pyproject.toml        # Project configuration, dependencies, entry points
└── README.md             # User-facing documentation
```

---

## Development Workflow

### Critical Rules - Must Follow

1. **Always run formatter and linter before considering work complete**
   ```bash
   scripts/format          # Format all code
   scripts/lint            # Check for linting issues
   ```

2. **Run tests after making changes**
   ```bash
   scripts/test            # Run full test suite with coverage
   # OR for specific tests:
   .venv/bin/python3 -m pytest tests/test_plugins.py -v
   ```

3. **Check test results against baseline**
   - Current baseline: 12 test failures (pre-existing, not related to plugin work)
   - Any NEW failures must be investigated and fixed
   - Test output format: `X failed, Y passed, Z skipped`

4. **Virtual environment location**: `.venv/` (already created)
   - Python executable: `.venv/bin/python3`
   - Pytest: `.venv/bin/pytest`
   - Package installation: `.venv/bin/pip install -e .`

5. **After modifying entry points in pyproject.toml**
   ```bash
   .venv/bin/pip install -e .  # Reinstall to register entry points
   ```

### Code Style Requirements

- **Formatter**: ruff (configured in pyproject.toml)
- **Linter**: ruff (configured in pyproject.toml)
- **Line length**: 100 characters (configured)
- **Type hints**: Use where appropriate
- **Docstrings**: Required for public methods and classes

### Testing Requirements

- **Test framework**: pytest
- **Coverage tool**: pytest-cov
- **Coverage requirements**: Aim for high coverage on new code
- **Test location**: `tests/` directory mirrors `src/` structure
- **Plugin tests**: Both in `tests/test_plugins.py` and `plugins/*/tests/`

---

## Plugin System Architecture

### Overview

The plugin system provides hooks at various points in the download lifecycle, allowing external code to extend icloudpd functionality without modifying core code.

### Key Concepts

1. **Hook-based architecture**: Plugins implement hook methods that are called at specific lifecycle events
2. **Entry point registration**: Plugins register via Python entry points in pyproject.toml
3. **Plugin discovery**: PluginManager discovers both bundled and pip-installed plugins
4. **Multiple plugins**: Multiple plugins can run concurrently
5. **Error isolation**: Plugin errors don't crash the main application

### Hook Lifecycle

```
For each photo in library:
    For each size variant (ORIGINAL, MEDIUM, THUMB, etc.):
        [Download or check if exists]
        → on_download_exists() OR on_download_downloaded()
        → on_download_complete()  [ALWAYS runs]

        [If live photo]:
            → on_download_exists_live() OR on_download_downloaded_live()
            → on_download_complete_live()

    → on_download_all_sizes_complete()  [KEY HOOK - process all accumulated files]

[After all photos]:
    → on_run_completed()
```

### Critical Hook Parameter: `requested_size`

**IMPORTANT CONCEPT**: All per-size hooks receive `requested_size` parameter.

**Why it exists**:
- During download, if a requested size doesn't exist, icloudpd falls back to ORIGINAL
- The filename uses the fallback size (e.g., no suffix for ORIGINAL)
- But plugins need to know what the user originally requested
- This is tracked by the loop variable rename in src/icloudpd/base.py:

```python
for requested_size in primary_sizes:
    download_size = requested_size  # Preserve what was requested
    if download_size not in versions:
        download_size = AssetVersionSize.ORIGINAL  # Fallback for filename

    # Filename uses download_size (fallback) - upstream behavior
    filename = calculate_version_filename(..., download_size, ...)

    # Plugins get requested_size - they know what user wanted
    plugin_manager.call_hook("on_download_exists",
        requested_size=requested_size,  # What user asked for
        ...
    )
```

**Rule**: Never change this to affect filenames - that's upstream behavior that must be preserved.

### Hook Signatures (Complete Reference)

All hooks use `requested_size` parameter (not `download_size`):

```python
def on_download_exists(
    self,
    download_path: str,
    photo_filename: str,
    requested_size: VersionSize,  # Note: requested_size, not download_size
    photo: PhotoAsset,
    dry_run: bool,
) -> None:
    """Called when file already exists"""

def on_download_downloaded(
    self,
    download_path: str,
    photo_filename: str,
    requested_size: VersionSize,
    photo: PhotoAsset,
    dry_run: bool,
) -> None:
    """Called after file downloaded"""

def on_download_complete(
    self,
    download_path: str,
    photo_filename: str,
    requested_size: VersionSize,
    photo: PhotoAsset,
    dry_run: bool,
) -> None:
    """Called after size processed (ALWAYS runs)"""

# Live photo versions (same signature):
def on_download_exists_live(...)
def on_download_downloaded_live(...)
def on_download_complete_live(...)

def on_download_all_sizes_complete(
    self,
    photo: PhotoAsset,
    dry_run: bool,
) -> None:
    """Called after ALL sizes complete - KEY HOOK for processing"""

def on_run_completed(
    self,
    dry_run: bool,
) -> None:
    """Called when entire run completes"""
```

### Plugin Implementation Pattern (Accumulator Pattern)

**CRITICAL PATTERN**: Plugins should accumulate file information in per-size hooks, then process in `on_download_all_sizes_complete`:

```python
class MyPlugin(IcloudpdPlugin):
    def __init__(self):
        self.current_photo_files = []  # Accumulator for current photo
        self.total_photos = 0

    def on_download_exists(self, download_path, photo_filename, requested_size, photo, dry_run):
        # ACCUMULATE - don't process yet
        self.current_photo_files.append({
            'path': download_path,
            'size': requested_size.value,
            'status': 'existed'
        })

    def on_download_downloaded(self, download_path, photo_filename, requested_size, photo, dry_run):
        # ACCUMULATE - don't process yet
        self.current_photo_files.append({
            'path': download_path,
            'size': requested_size.value,
            'status': 'downloaded'
        })

    def on_download_all_sizes_complete(self, photo, dry_run):
        # PROCESS all accumulated files for this photo
        self.total_photos += 1

        # Do something with all files
        for file_info in self.current_photo_files:
            process_file(file_info)

        # CRITICAL: Clear accumulator for next photo
        self.current_photo_files.clear()
```

**Why this pattern**:
- You get all size variants together (original, medium, thumb, etc.)
- You can stack/group related files
- You have complete photo metadata
- You process everything atomically

### Plugin Registration (Entry Points)

In `pyproject.toml`:

```toml
[project.entry-points."icloudpd.plugins"]
demo = "icloudpd.plugins.demo:DemoPlugin"
immich = "plugins.immich.immich:ImmichPlugin"
```

**Important**: After changing entry points, run `.venv/bin/pip install -e .`

### Plugin Files to Update When Changing Hook Signatures

If you need to add/modify hook signatures, update ALL of these:

1. `src/icloudpd/plugins/hooks.py` - Protocol definitions (the interface contract)
2. `src/icloudpd/plugins/base.py` - Base class default implementations
3. `src/icloudpd/base.py` - Hook call sites in download orchestration
4. `src/icloudpd/plugins/demo.py` - Demo plugin implementation
5. `plugins/immich/immich.py` - Immich plugin implementation
6. `tests/test_plugins.py` - Test mocks and test calls
7. `docs/plugins.md` - Documentation

---

## Critical Files Deep Dive

### src/icloudpd/base.py

**Purpose**: Core download orchestration - this is where photos are downloaded

**Plugin Integration Points**:
- Line ~717: Main download loop - `for requested_size in primary_sizes:`
- Line ~775: Hook call after file exists check
- Line ~843: Hook call after download
- Line ~886: Hook call after size complete
- Similar patterns for live photos

**Critical Code Pattern**:
```python
for requested_size in primary_sizes:
    download_size = requested_size  # Track what user requested

    # Fallback logic (upstream behavior - DO NOT MODIFY)
    if download_size not in versions:
        download_size = AssetVersionSize.ORIGINAL

    # Filename uses download_size (may be fallback)
    filename = calculate_version_filename(..., download_size, ...)

    # Hook uses requested_size (what user asked for)
    plugin_manager.call_hook("on_download_exists",
        requested_size=requested_size,
        ...
    )
```

**Important**: Plugin manager is threaded through function calls:
- `download_directory()` receives `plugin_manager` parameter
- `download_photo()` receives `plugin_manager` parameter
- Hooks are called via `plugin_manager.call_hook()`

### src/icloudpd/plugins/manager.py

**Purpose**: Plugin lifecycle management

**Key Methods**:
- `discover()`: Finds plugins via entry points and directory scanning
- `enable(name, config)`: Enables and configures a plugin
- `call_hook(hook_name, **kwargs)`: Calls a hook on all enabled plugins
- `cleanup()`: Cleanup all plugins on shutdown

**Error Handling**: Plugins errors are logged but don't crash the application

### pyproject.toml

**Purpose**: Project configuration

**Critical Sections**:

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "src"]  # Note: "plugins" removed to avoid discovery issues
pythonpath = ["src"]           # Note: "." removed - was breaking imports

[project.entry-points."icloudpd.plugins"]
demo = "icloudpd.plugins.demo:DemoPlugin"
immich = "plugins.immich.immich:ImmichPlugin"
```

**Warning**: Adding `"."` to pythonpath breaks imports. Don't do it.

---

## Common Development Tasks

### Adding a New Hook

1. Define in `src/icloudpd/plugins/hooks.py` (Protocol class)
2. Add default implementation in `src/icloudpd/plugins/base.py`
3. Call in `src/icloudpd/base.py` at appropriate lifecycle point
4. Implement in `src/icloudpd/plugins/demo.py` (reference)
5. Update `plugins/immich/immich.py` if needed
6. Add tests in `tests/test_plugins.py`
7. Document in `docs/plugins.md`
8. Run `scripts/format` and `scripts/lint`
9. Run `scripts/test` and verify no new failures

### Modifying Hook Signatures

**Example**: Changing parameter name from `download_size` to `requested_size`

Files to update:
1. `src/icloudpd/plugins/hooks.py` - Protocol signature
2. `src/icloudpd/plugins/base.py` - Base class signature
3. `src/icloudpd/base.py` - Hook call sites (parameter name in call)
4. `src/icloudpd/plugins/demo.py` - All hook implementations
5. `plugins/immich/immich.py` - All hook implementations
6. `tests/test_plugins.py` - MockPlugin class and all test calls
7. `docs/plugins.md` - All documentation and examples

Run tests after each file to catch issues early.

### Creating a New Plugin

1. Create plugin file (either in `src/icloudpd/plugins/` or `plugins/name/`)
2. Inherit from `IcloudpdPlugin`
3. Implement required properties: `name`, `version`, `description`
4. Implement desired hook methods
5. Add entry point in `pyproject.toml`
6. Run `.venv/bin/pip install -e .`
7. Create tests
8. Document usage

### Running Tests

```bash
# Full suite with coverage
scripts/test

# Specific test file
.venv/bin/python3 -m pytest tests/test_plugins.py -v

# Specific test class
.venv/bin/pytest tests/test_plugins.py::TestDemoPlugin -v

# Specific test method
.venv/bin/pytest tests/test_plugins.py::TestDemoPlugin::test_demo_plugin_accumulation -v

# Quick run without coverage
.venv/bin/python3 -m pytest tests/ --tb=no -q
```

**Baseline Test Results** (as of 2026-01-02):
- 12 failed (pre-existing, not plugin-related)
- 305 passed
- 2 skipped

**Test Failures to Ignore** (baseline):
- 7 autodelete tests
- 1 CLI parser test
- 2 download tests
- 2 ID7 download tests

### Debugging Test Failures

1. Run with verbose output: `-v` flag
2. Show full traceback: remove `--tb=no`
3. Run single test to isolate
4. Check if failure existed before your changes (compare to baseline)
5. Common issues:
   - Entry points not registered (run `pip install -e .`)
   - Parameter name mismatches (check all 7 files)
   - Import errors (check pythonpath in pyproject.toml)

---

## Architectural Decisions and Rationale

### Why `requested_size` Instead of `download_size`

**Problem**: Original code mutated loop variable during fallback, losing information about what user requested.

**Solution**: Rename loop variable to `requested_size`, preserve it separately from `download_size`:
```python
for requested_size in primary_sizes:
    download_size = requested_size
    # download_size may change (fallback), requested_size doesn't
```

**Rationale**:
- Minimal change to core behavior
- Preserves upstream filename behavior (uses fallback size)
- Gives plugins access to both values
- Plugin hooks receive `requested_size` (what user wanted)
- Filenames still use `download_size` (what was actually downloaded)

### Why Accumulator Pattern for Plugins

**Problem**: Hooks are called per-size, but plugins often need all sizes together.

**Solution**: Accumulate in instance variables, process in `on_download_all_sizes_complete`.

**Rationale**:
- Natural fit for operations like stacking, uploading groups
- Access to complete photo metadata
- Atomic processing of related files
- Clear lifecycle (accumulate → process → clear)

### Why Separate `plugins/` Directory

**Design Decision**: Bundled plugins live in `plugins/`, not `src/icloudpd/plugins/`

**Rationale**:
- Clear separation between infrastructure (src) and implementations (plugins)
- Plugins can be large (Immich is 1672 lines)
- Plugin-specific dependencies don't pollute core
- Makes it clear which plugins are "official" vs user-contributed
- Still registered via entry points like external plugins

### Why Entry Points for Plugin Discovery

**Design Decision**: Use Python entry points, not directory scanning alone

**Rationale**:
- Standard Python plugin mechanism
- Allows pip-installed external plugins
- Works with virtual environments
- Automatic discovery without manual registration
- Familiar to Python developers

---

## Common Pitfalls and Solutions

### Pitfall 1: Forgetting to Reinstall After Entry Point Changes

**Symptom**: Plugin not discovered, tests fail with "plugin not found"

**Solution**:
```bash
.venv/bin/pip install -e .
```

### Pitfall 2: Adding "." to pythonpath

**Symptom**: 119 test failures, import errors everywhere

**Solution**: Remove `"."` from pythonpath in pyproject.toml. Use only `["src"]`

### Pitfall 3: Inconsistent Parameter Names Across Files

**Symptom**: `TypeError: got an unexpected keyword argument 'download_size'`

**Solution**: Update all 7 files when changing hook signatures (see checklist above)

### Pitfall 4: Trying to "Fix" Upstream Behavior

**Symptom**: Test failures in test_download_photos.py, filename behavior changes

**Solution**: Don't modify how filenames are generated. That's upstream behavior. Only change what plugins receive.

**Example of what NOT to do**:
```python
# DON'T DO THIS - changes filename behavior
filename = calculate_version_filename(..., requested_size, ...)  # WRONG
```

**Correct approach**:
```python
# DO THIS - preserves filename behavior, gives plugins info
filename = calculate_version_filename(..., download_size, ...)  # Correct
plugin_manager.call_hook(..., requested_size=requested_size, ...)  # Correct
```

### Pitfall 5: Not Clearing Accumulators

**Symptom**: Plugin processes files from previous photos, data leaks between photos

**Solution**: Always clear accumulators in `on_download_all_sizes_complete`:
```python
def on_download_all_sizes_complete(self, photo, dry_run):
    # Process files...

    # CRITICAL: Clear for next photo
    self.current_photo_files.clear()
```

---

## Testing Philosophy

### What to Test

1. **Plugin discovery and registration**
2. **Hook calls at correct lifecycle points**
3. **Plugin receives correct parameters**
4. **Error handling (plugin errors don't crash app)**
5. **Plugin configuration from CLI args**
6. **Accumulator pattern (accumulate → process → clear)**

### What NOT to Test in Plugins

1. **Core download logic** - that's tested elsewhere
2. **Filename generation** - that's upstream
3. **iCloud API** - use mocks

### Mock Pattern for Tests

```python
from unittest.mock import MagicMock
from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import AssetVersionSize

# Mock photo
mock_photo = MagicMock(spec=PhotoAsset)
mock_photo.filename = "test.jpg"
mock_photo.id = "ABC123"
mock_photo._asset_record = {"fields": {"isFavorite": {"value": 1}}}

# Call hook
plugin.on_download_downloaded(
    download_path="/path/test.jpg",
    photo_filename="test.jpg",
    requested_size=AssetVersionSize.ORIGINAL,
    photo=mock_photo,
    dry_run=False
)

# Verify
assert len(plugin.current_photo_files) == 1
```

---

## Git Workflow

### Branches

- `master` - Main branch
- `feature/*` - Feature branches
- Current work: `feature/plugins`

### Before Committing

**MANDATORY CHECKLIST**:
```bash
# 1. Format code
scripts/format

# 2. Lint code
scripts/lint

# 3. Run tests
scripts/test

# 4. Verify no new failures (compare to baseline: 12 failures)

# 5. If all pass, stage and commit
git add .
git commit -m "Descriptive message"
```

### Commit Message Style

- Be descriptive
- Reference issues if applicable
- Explain WHY, not just WHAT

---

## Performance Considerations

### Plugin Performance

- Hooks are called for EVERY size variant of EVERY photo
- Keep per-size hooks fast (accumulate only)
- Do expensive work in `on_download_all_sizes_complete`
- Consider batch processing for network operations

### Test Performance

- Full test suite takes ~30-50 seconds
- Use `-k` flag to run subset during development
- Use `--tb=no -q` for quick feedback
- Run full suite before committing

---

## Documentation Locations

### For Users
- `README.md` - Getting started, usage
- `docs/plugins.md` - Plugin development guide

### For Developers
- `src/icloudpd/plugins/hooks.py` - Docstrings on Protocol
- `src/icloudpd/plugins/base.py` - Docstrings on base class
- `src/icloudpd/plugins/demo.py` - Reference implementation with comments
- This file (`AI_AGENT_CONTEXT.md`) - Comprehensive context

---

## Quick Reference Commands

```bash
# Setup
.venv/bin/pip install -e .

# Development
scripts/format                          # Format code
scripts/lint                            # Lint code
scripts/test                            # Run tests with coverage

# Testing
.venv/bin/pytest tests/ -v              # Verbose tests
.venv/bin/pytest tests/ --tb=no -q      # Quick feedback
.venv/bin/pytest tests/test_plugins.py::TestDemoPlugin -v  # Specific test

# Debugging
.venv/bin/pytest tests/test_plugins.py -v --tb=short  # Short traceback
.venv/bin/pytest tests/test_plugins.py -v -s          # Show print statements

# Coverage
scripts/test                            # HTML report in htmlcov/
open htmlcov/index.html                 # View coverage report
```

---

## Environment Information

**Python Version**: 3.13.3
**Platform**: Linux
**Virtual Environment**: `.venv/` (already created)
**Working Directory**: `/home/jasper/src/svn/icloud_photos_downloader/`

---

## When in Doubt

1. **Check the demo plugin** (`src/icloudpd/plugins/demo.py`) - it's the reference implementation
2. **Read the plugin guide** (`docs/plugins.md`) - comprehensive documentation
3. **Look at existing tests** (`tests/test_plugins.py`) - shows expected patterns
4. **Run the linter** - it catches many issues automatically
5. **Compare to baseline** - 12 failures is expected, more is a problem

---

## Critical "Never Do This" List

1. ❌ Never add `"."` to pythonpath in pyproject.toml
2. ❌ Never modify filename generation logic in base.py (upstream behavior)
3. ❌ Never commit without running `scripts/format` and `scripts/lint`
4. ❌ Never change hook signatures without updating all 7 files
5. ❌ Never process files in per-size hooks (use accumulator pattern)
6. ❌ Never forget to clear accumulators in `on_download_all_sizes_complete`
7. ❌ Never use `download_size` parameter name in hooks (use `requested_size`)
8. ❌ Never skip running tests before committing
9. ❌ Never forget to reinstall after changing entry points

---

## Version History

**2026-01-02**: Initial creation
- Plugin system implemented
- Hook parameter standardized to `requested_size`
- Immich plugin fully functional
- Test baseline: 12 failures, 305 passed, 2 skipped

---

## Contact Context

**Project Maintainer**: External (upstream repository)
**This Fork/Branch**: Jasper (feature/plugins branch)
**Development Approach**: TDD with Claude Code AI assistant

---

**End of AI Agent Context Document**

This document should be read in full before making any changes to the codebase. It contains critical information that will prevent common mistakes and save significant debugging time.
