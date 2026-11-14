# Execution-plan template (the layer's sections)

Merge these sections into the plan produced by the base plan-writing skill: the system instructions
and authority matrix go at the top, Phase 0 before the first task, a receipt at the end of every task,
the adversarial review and final delivery at the end. Repeat phases only as the work needs.

## 🚨 System instructions for the executor — read first

- This plan is self-contained; do not depend on a previous chat. Revalidate live source and tool
  schemas before any mutation.
- Output exactly three strategy sentences before file edits; then the read-only preflight. Preserve
  dirty work and isolate authorized changes.
- Prefer the environment's native read/search/edit tools; use the shell for version control, tests and
  execution. Do not guess tool schemas, rewrite files from fragments, or ship placeholder code.
- Respect the authority matrix. Never infer a merge, release, global install or live-service permission
  from edit or branch permission.
- A phase requires real receipts; a failure means STOP, diagnose, fix, rerun. Show a known-bad isolated
  fixture failing and a good one passing where appropriate.
- No secrets in logs or receipts. Say "not tested" when a test cannot safely run.

## 📌 Context and objectives

**Project and verified source / discovery method:** …
**Current behaviour → required behaviour:** (entry-point and state matrix)
**Evidence and unknowns:** each item labelled live / dated / decision / unknown, with its probe.
**Hard constraints and non-goals:** architecture, cost/privacy/security, compatibility.
**Acceptance criteria:** observable outcomes; explicitly deferred items.

## 🔒 Authority matrix

| Operation | Allowed now / gated / permission needed / prohibited | Evidence or gate |
|---|---|---|
| Read-only inspection | | source check |
| Modify isolated files / branch | | dirty-work preservation |
| Install project-scoped dependency | | pinned, project environment |
| Commit / publish a feature branch | | tests + staged diff review |
| Merge / tag / release / deploy | | separate authorization |
| Live APIs / downloads / deletion / process control | | safe fixture or explicit approval |

## 🛑 Phase 0 — forced preflight

**Objective:** correct source, tools, branch and work-preservation strategy.
**Actions:** three-sentence strategy FIRST; then read-only inventory, local instructions, live status,
baseline test run. Preserve relevant dirty files before isolated edits. Stop on unresolved ambiguity.
**🧪 Receipt 0:** read-only command output, source map, dirty-path reconciliation, baseline counts.

## Per task / phase (append to each task of the base plan)

**Discriminant:** the known-bad input or isolated mutation that must fail; the good case that passes.
**🧪 Receipt:** raw non-secret stdout/stderr, exit status, state assertions; failure → STOP / diagnose
/ fix / rerun.

## 🧨 Adversarial review

For each material risk: **tempting shortcut → plausible false success → concrete harm → rule →
detecting test/receipt**. Cover source provenance, dirty work, tool selection, tests, side effects,
compatibility, process cleanup and authorization. List the risks that cannot be tested safely.

## 🏁 Final review and delivery

What is implemented versus merely planned? Which receipts ran? Which tests did not? Is user work
preserved? Were secrets or global/live systems touched? Do direct and interactive behaviour match the
contract? Did the run stop before its authorization boundary? Was the delivered artifact reread?
