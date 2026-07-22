# Case Script Solidification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Android-only case script generation for passed cases and a script-first execution path with agent fallback, while ensuring exploration does not pollute pre-execution app state.

**Architecture:** Extend `scripts/orchestrate.py` with three focused capabilities: script path discovery/execution, script file generation from high-confidence case results, and post-exploration app cleanup. Keep existing device grouping and batching unchanged, and route script hits through a thin per-case executor that falls back to the current agent path on script failure.

**Tech Stack:** Python 3, existing orchestrator/test suite, Appium-adjacent shell/device commands, pytest.

---

### Task 1: Add regression tests for exploration cleanup

**Files:**
- Modify: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_run_stops_apps_after_exploration(monkeypatch):
    monkeypatch.setattr(orchestrate, "load_devices", lambda app_id: {
        "android": [{"udid": "a1", "name": "android-dev"}],
        "ios": [{"udid": "i1", "name": "ios-dev"}],
    })
    monkeypatch.setattr(orchestrate, "download_file", lambda url, dest: True)
    monkeypatch.setattr(orchestrate, "install_android", lambda path, udid: True)
    monkeypatch.setattr(orchestrate, "install_ios", lambda path, udid: True)
    monkeypatch.setattr(orchestrate, "fetch_cases", lambda app_id: [])
    monkeypatch.setattr(orchestrate, "run_exploration", lambda *args, **kwargs: None)

    stopped = []
    monkeypatch.setattr(orchestrate, "reset_apps_after_exploration",
                        lambda app_id, android_devices, ios_devices: stopped.append(
                            (app_id, tuple(android_devices), tuple(ios_devices))
                        ))

    with patch("orchestrate.run_status"), patch("orchestrate._notify"):
        orchestrate._run(
            app_id="gaotu",
            version="5.91.90",
            apk_url="https://example.com/app.apk",
            ipa_url="https://example.com/app.ipa",
            platforms={"android", "ios"},
            run_id="r1",
        )

    assert stopped == [("gaotu", ("a1",), ("i1",))]


def test_reset_apps_after_exploration_best_effort(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrate, "_stop_android_app",
                        lambda udid, pkg: calls.append(("android", udid, pkg)) or True)
    monkeypatch.setattr(orchestrate, "_stop_ios_app",
                        lambda udid, bundle_id: calls.append(("ios", udid, bundle_id)) or False)

    orchestrate.reset_apps_after_exploration("gaotu", ["a1"], ["i1"])

    assert calls == [
        ("android", "a1", "com.gaotu100.superclass"),
        ("ios", "i1", "com.gaotu100.superclass"),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py -k "stops_apps_after_exploration or reset_apps_after_exploration_best_effort"`

Expected: FAIL because `reset_apps_after_exploration` and stop helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def _stop_android_app(udid: str, pkg: str) -> bool:
    ...


def _stop_ios_app(udid: str, bundle_id: str) -> bool:
    ...


def reset_apps_after_exploration(app_id: str, android_devices: list, ios_devices: list):
    ...
```

Call it immediately after `run_exploration(...)` and before `fetch_cases(...)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py -k "stops_apps_after_exploration or reset_apps_after_exploration_best_effort"`

Expected: PASS


### Task 2: Add regression tests for script generation

**Files:**
- Modify: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_generate_case_script_for_passed_high_confidence_case(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec1",
        "name": "case one",
        "module": "首页",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "PRECOND", "text": "账号：12345679000"},
            {"type": "ASSERT", "text": "打开首页", "verify_method": "id",
             "evidence": "com.gaotu100.superclass:id/home", "confidence": "high", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case)

    assert path is not None
    content = Path(path).read_text()
    assert "META" in content
    assert "rec1" in content
    assert "com.gaotu100.superclass:id/home" in content


def test_generate_case_script_skips_low_confidence_case(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", str(tmp_path))
    case = {
        "record_id": "rec2",
        "name": "case two",
        "module": "首页",
        "platform": "Android",
        "device": "a1",
        "passed": True,
        "steps": [
            {"type": "ASSERT", "text": "视觉判断", "verify_method": "vision",
             "evidence": "/tmp/shot.png", "confidence": "low", "passed": True},
        ],
    }

    path = orchestrate.generate_case_script("gaotu", "android", case)

    assert path is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py -k "generate_case_script"`

Expected: FAIL because script generation helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def case_script_path(app_id: str, platform: str, record_id: str) -> str:
    ...


def should_generate_case_script(case: dict) -> bool:
    ...


def generate_case_script(app_id: str, platform: str, case: dict):
    ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py -k "generate_case_script"`

Expected: PASS


### Task 3: Add regression tests for script-first execution with fallback

**Files:**
- Modify: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_execute_case_prefers_existing_script(monkeypatch):
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": True, "name": "case", "steps": []})

    agent_called = []
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: agent_called.append(True))

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu",
        platform="android",
        udid="a1",
        entry=entry,
        version="5.91.90",
        current_account="12345679000",
    )

    assert result["passed"] is True
    assert agent_called == []


def test_execute_case_falls_back_to_agent_and_regenerates_script(monkeypatch):
    entry = {"record_id": "rec1", "name": "case", "module": "首页", "steps": []}
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"passed": False, "note": "bad script", "steps": []})

    generated = []
    monkeypatch.setattr(orchestrate, "generate_case_script",
                        lambda *args, **kwargs: generated.append(True) or "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "execute_case_via_agent",
                        lambda *args, **kwargs: {"passed": True, "record_id": "rec1", "name": "case", "module": "首页", "platform": "Android", "device": "a1", "steps": []})

    result = orchestrate.execute_case_with_fallback(
        app_id="gaotu",
        platform="android",
        udid="a1",
        entry=entry,
        version="5.91.90",
        current_account="12345679000",
    )

    assert result["passed"] is True
    assert generated == [True]
    assert result["script_fallback"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py -k "prefers_existing_script or falls_back_to_agent"`

Expected: FAIL because the fallback executor does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def find_case_script(app_id: str, platform: str, record_id: str) -> str:
    ...


def run_case_script(...):
    ...


def execute_case_via_agent(...):
    ...


def execute_case_with_fallback(...):
    ...
```

Use a result shape compatible with existing case JSON and include internal flags like `script_source` / `script_fallback`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py -k "prefers_existing_script or falls_back_to_agent"`

Expected: PASS


### Task 4: Wire the new behavior into orchestrator flow

**Files:**
- Modify: `scripts/orchestrate.py`
- Modify: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_orchestrate.py`

- [ ] **Step 1: Write the failing integration test**

```python
def test_execute_device_batches_uses_script_first_results(monkeypatch, tmp_path):
    group = {
        "platform": "Android",
        "entries": [
            {"record_id": "rec1", "name": "c1", "module": "首页", "steps": []},
        ],
    }
    monkeypatch.setattr(orchestrate, "find_case_script", lambda *args, **kwargs: "/tmp/rec1.py")
    monkeypatch.setattr(orchestrate, "run_case_script",
                        lambda *args, **kwargs: {"record_id": "rec1", "name": "c1", "module": "首页", "platform": "Android", "device": "a1", "passed": True, "steps": []})
    monkeypatch.setattr(orchestrate, "write_results_to_table", lambda *args, **kwargs: None)

    results = orchestrate.execute_device_batches(
        app_id="gaotu",
        udid="a1",
        group=group,
        version="5.91.90",
        run_id="r1",
        result_dir=str(tmp_path),
        batch_size=20,
    )

    assert results[0]["record_id"] == "rec1"
    assert results[0]["passed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py -k "uses_script_first_results"`

Expected: FAIL because `execute_device_batches` only knows the agent path today.

- [ ] **Step 3: Write minimal implementation**

```python
def execute_device_batches(...):
    ...
    # per case inside each batch:
    result = execute_case_with_fallback(...)
    ...
```

Keep batch ordering, result writeback, and account handoff behavior intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py -k "uses_script_first_results"`

Expected: PASS


### Task 5: Full verification

**Files:**
- Test: `scripts/tests/test_orchestrate.py`
- Test: `scripts/tests/test_run_status.py`

- [ ] **Step 1: Run targeted full suite**

Run: `python3 -m pytest -q scripts/tests/test_orchestrate.py scripts/tests/test_run_status.py`

Expected: PASS with 0 failures

- [ ] **Step 2: Inspect diff for scope control**

Run: `git diff -- scripts/orchestrate.py scripts/tests/test_orchestrate.py scripts/tests/test_run_status.py docs/superpowers/plans/2026-07-10-case-script-solidification.md`

Expected: only script-solidification and exploration-cleanup related changes
