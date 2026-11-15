# PR245 Complete GenOffice Skills Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Copy all fixed-source GenOffice skills and editor skill/prompt sources and expose real skills and guides through the existing Agno hosts.
**Architecture:** Keep a byte-identical vendored snapshot with commit, Git blob and SHA256 provenance; never execute vendored desktop TS. Use Agno native Skills/LocalSkills for all43 SKILL.md packages and augment per-run Office agents with a host capability boundary. Preserve upstream XLSX guide bytes and return them with separately labelled native adapter notes.
**Tech Stack:** Agno3.1.12, Python, existing native Office agents, pytest.
**Spec:** approved docs/superpowers/specs/2026-11-15-pr245-agno-tool-parity-design.md plus user instruction “技能也全部抄过来”.

## Global Constraints

Fixed upstream f8c17004fb730df11f0f743164ffd8b4281bb38c. Copy all skills/ files including translations, all six renderer ai directories, common agent-core sources, PPTX operation prompts and skill import/CLI integration definitions. Root license/notice retained when present. Source skill copy is not desktop IPC/CLI execution support. Use framework Skills, no custom skill parser/executor. Maintain document authorization, source identity, read-only vs candidate behavior and explicit acceptance; no repeated full suite.

## Review Focus

- Manifest must exhaustively contain every43 skill package and all source skill files selected from fixed tree; no rewritten SKILL.md.
- Upstream extended category/scenarios/quickPrompts frontmatter must not silently drop skills during Agno loading.
- Existing custom agent skills and document tools survive augmentation; per-run mutation does not modify shared base agents.
- CLI and write instructions never imply tools exist, alter authorization or allow auto-save/auto-apply in read-only tasks.
- All11 source XLSX guides are accessible; source tool formats and unsupported capabilities are labelled alongside actual local mappings.

### Task1: Immutable complete snapshot

Create smart_reporting/office/vendor/genoffice with original paths and SOURCE-MANIFEST.json, and provenance README. Download from fixed ref, verify each blob against fixed-tree Git SHA1 before write, record SHA256 and byte size. No TS import execution.
- [x] Copy source files, licenses and all43 SKILL.md packages; verify all selected tree entries copied.
- [x] Add inventory tests comparing required complete43 names and manifest byte/hash identities; check no source scripts silently activated.

### Task2: Agno skill runtime

Create office/ai_skills.py. Interface office_skills() -> agno.skills.Skills; attach_office_skills(agent) preserves existing Skills loaders and document tools, adds native Skills and a clear native-host instruction after existing guidance. Native LocalSkills(validate=False) is necessary because source adds category/scenarios/quickPrompts beyond Agent Skills allowed frontmatter; source is fixed and hash-verified, tests assert every parsed name/nonempty description/instructions. All43 packages remain intact including CLI skill, but missing CLI tools must be described as unavailable.
- [x] Add failing runtime and real Agno tool-call tests before implementation.
- [x] Implement native Skills wiring at nine existing source-enriched native planners plus Word task MCP transport and Office knowledge host; no search reranker or filename-only agent.
- [x] Verify get_skill_instructions tool and metadata are in real Agent loop, existing tools retained, unselected skill bodies stay out of prompt until requested.

### Task3: Full XLSX guides

Modify WorkbookAIToolkit.load_guide to support all11 upstream guide keys (including formatting/financial-formatting/shape-image/data-attribution). Return original guide text plus explicitly separated adapter/capability notes; retain existing per-key local mappings and no blanket source auto-apply semantics.
- [x] Add failing tests for previously missing keys and exact original guide prefix/content and invalid-key atomic rejection.
- [x] Implement source guide loader and host notes, preserving response dict shape.
- [x] Run affected runtime/source/planner/guide tests; independent review, source evidence and PR update.
