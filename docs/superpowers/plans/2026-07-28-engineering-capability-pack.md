# Engineering Capability Pack Copier Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the independently released `agent-skills/engineering` capability pack and converge all coding-agent state through one idempotent `mise run agent-sync` operation.

**Architecture:** Extend the existing `include_agent_layer` scaffold with one default-on `include_engineering_workflow` answer. Keep the dependency rendering in the existing APM partial and the convergence implementation in the existing mise partial. Tests override hidden package source/ref answers with a local APM fixture, while generated production projects point at the package-scoped Git tag.

**Tech Stack:** Copier 9.17, Jinja templates, mise, APM 0.26.0, Python `unittest`

## Global Constraints

- `mise run agent-sync` is the sole public convergence operation.
- Default mode reconciles the manifest and lock; `--refresh` refreshes dependency resolution; `--frozen` verifies committed state.
- The production dependency is `kzarzycki/agent-skills/engineering` at `engineering-v0.2.0`.
- Claude Code and Codex are the current conformance targets.
- GitHub Copilot and Cursor remain explicit adapter and conformance-test extension seams.
- The generated repository must work without dotagents or user-global skill/plugin state.
- `include_engineering_workflow` defaults to true only when `include_agent_layer` is enabled.

---

### Task 1: Render one optional engineering capability-pack dependency

**Files:**
- Modify: `copier.yml`
- Modify: `templates/_base/_apm_yml.part`
- Modify: `templates/_base/_copier_answers.yml.jinja`
- Test: `tests/test_agent_layer_generation.py`

**Interfaces:**
- Consumes: existing `include_mise` and `include_agent_layer` Copier answers
- Produces: `include_engineering_workflow: bool`, hidden `engineering_capability_source: str`, hidden `engineering_capability_ref: str`, and one APM dependency entry

- [ ] **Step 1: Write failing render tests**

Add tests that render the enabled default and explicit disabled variants. Assert the enabled `apm.yml` contains exactly one dependency:

```yaml
dependencies:
  apm:
    - git: kzarzycki/agent-skills/engineering
      ref: engineering-v0.2.0
```

Assert the disabled variant keeps `dependencies.apm` empty, and that `.copier-answers.yml` records the public boolean without exposing hidden fixture controls.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_agent_layer_generation.AgentLayerGenerationTest.test_engineering_workflow_is_enabled_by_default \
  tests.test_agent_layer_generation.AgentLayerGenerationTest.test_engineering_workflow_can_be_disabled
```

Expected: failures because the Copier answer and dependency do not exist.

- [ ] **Step 3: Add the smallest template implementation**

Add the conditional Copier answer:

```yaml
include_engineering_workflow:
  type: bool
  default: true
  when: "{{ include_mise and include_agent_layer }}"
  help: Add the standard engineering capability pack?
```

Add hidden source/ref answers with production defaults. Render a Git dependency when the ref is non-empty and a scalar local-path dependency when tests set an empty ref.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the two tests from Step 2. Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add copier.yml templates/_base/_apm_yml.part \
  templates/_base/_copier_answers.yml.jinja tests/test_agent_layer_generation.py
git commit -m "feat: scaffold engineering capability pack"
```

### Task 2: Make `agent-sync` the single convergence state machine

**Files:**
- Modify: `templates/_base/_mise_agent_tasks.part`
- Modify: `tests/test_agent_mise_tasks.py`
- Modify: `tests/test_agent_layer_generation.py`

**Interfaces:**
- Consumes: optional `--refresh` or `--frozen` after mise's `--`
- Produces: one shell state machine that installs, compiles, validates, audits, validates native Claude/Codex output, and validates fnox declarations

- [ ] **Step 1: Write failing task behavior tests**

Use real rendered `mise.toml` with fake `apm`/`fnox` executables. Add independent tests for these literal command sequences:

```text
default: apm install; apm compile; apm compile --validate; apm audit --ci --no-policy
refresh: apm install --refresh; apm compile; apm compile --validate; apm audit --ci --no-policy
frozen: apm install --frozen; apm audit --ci --no-policy; apm compile;
        apm compile --validate; apm audit --ci --no-policy
```

Also assert unknown flags and combined modes exit 2 with usage text and execute no APM command.

- [ ] **Step 2: Run the focused task suite and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_agent_mise_tasks
```

Expected: the refresh, frozen-audit, usage, and integrated-validation assertions fail.

- [ ] **Step 3: Implement argument parsing and convergence**

In `[tasks.agent-sync]`, accept zero or one argument, map `--refresh` and `--frozen`, and reject every other shape. Use APM 0.26.0:

```sh
case "$mode" in
  default) apm install ;;
  refresh) apm install --refresh ;;
  frozen) apm install --frozen; apm audit --ci --no-policy ;;
esac
apm compile
apm compile --validate
apm audit --ci --no-policy
```

Keep Claude JSON, Codex TOML, and optional fnox checks in this same task. Remove `agent-check`; the check would duplicate the convergence pipeline.

- [ ] **Step 4: Add frozen repository-state verification**

After compilation and audit, frozen mode checks tracked and untracked state only under APM-owned paths:

```text
apm.lock.yaml
AGENTS.md
CLAUDE.md
.agents/
.claude/
.codex/
.github/instructions/
```

Exit 1 and name the stale paths if compilation changed committed output.

- [ ] **Step 5: Run task and generation suites and verify GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_agent_mise_tasks tests.test_agent_layer_generation
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add templates/_base/_mise_agent_tasks.part \
  tests/test_agent_mise_tasks.py tests/test_agent_layer_generation.py
git commit -m "feat: converge agent configuration with one task"
```

### Task 3: Qualify enabled and disabled rendered repositories

**Files:**
- Create: `tests/fixtures/engineering/apm.yml`
- Create: `tests/fixtures/engineering/skills/wayfinder/SKILL.md`
- Modify: `tests/test_agent_layer_generation.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `skills/bootstrap-project/SKILL.md`
- Modify: `examples/agent-layer-mvp/mise.toml`
- Modify: `examples/agent-layer-mvp/tests/test_agent_layer_example.py`

**Interfaces:**
- Consumes: hidden empty-ref local-path dependency form and the `agent-sync` modes from Tasks 1–2
- Produces: an offline rendered-project E2E proving installation, Claude/Codex skill deployment, idempotence, frozen failure, and disabled rendering

- [ ] **Step 1: Write a failing enabled-render E2E**

Render with:

```python
include_engineering_workflow=True
engineering_capability_source=<absolute tests/fixtures/engineering path>
engineering_capability_ref=""
```

Initialize Git, commit the rendered state, run default `agent-sync`, and assert:

```text
.claude/skills/wayfinder/SKILL.md
.agents/skills/wayfinder/SKILL.md
apm.lock.yaml
```

Commit the converged state, run default sync again and assert no Git diff, then run frozen sync and assert success. Change the manifest and assert frozen exits nonzero.

- [ ] **Step 2: Run the E2E and verify RED**

Run the new test directly. Expected: failure because the fixture dependency and full state machine do not exist.

- [ ] **Step 3: Add the local fixture and finish the E2E**

Create a one-skill APM package named `engineering` containing a valid Wayfinder `SKILL.md`. Exercise the installed files, not fixture source text. Keep the fixture independent of user home configuration through temporary `HOME`, `XDG_*`, `MISE_*`, and APM cache paths.

- [ ] **Step 4: Update public and generated documentation**

Document:

```bash
mise run agent-sync
mise run agent-sync -- --refresh
mise run agent-sync -- --frozen
```

State that engineering workflow support is default-on and optional, the first run creates the lock, and generated repositories commit the manifest, lock, and deployed Claude/Codex skills. Keep the Copilot/Cursor extension steps.

- [ ] **Step 5: Update CI and the checked-in example**

Replace example/CI `agent-check` use with:

```bash
mise run agent-sync -- --frozen
```

Update the example's APM pin and task to 0.26.0 without adding the engineering dependency; the example remains a machine-binding demonstration, not a capability-pack release fixture.

- [ ] **Step 6: Run focused and full verification**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_agent_layer_generation tests.test_agent_mise_tasks \
  tests.test_bootstrap_local_source tests.test_version_contract
cd examples/agent-layer-mvp
mise install
mise run agent-sync -- --frozen
mise run test
mise run lint
```

Expected: root tests, frozen example convergence, behavioral tests, and lint all pass.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures tests .github/workflows/ci.yml README.md \
  skills/bootstrap-project/SKILL.md examples/agent-layer-mvp
git commit -m "test: qualify capability pack scaffold end to end"
```

## Self-review

- R1/R6–R10 map to Tasks 1–3.
- AC1–AC5 and AC20–AC23 map to the enabled/disabled render tests and offline E2E.
- The plan contains no deferred implementation placeholders.
- The package source/ref controls are fixture seams; the public consumer choice remains one boolean and one dependency.
