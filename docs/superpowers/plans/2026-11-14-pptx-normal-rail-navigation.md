# PPTX Normal rail navigation implementation plan

> Required: executing-plans; implement inline as assigned.

Goal: source-backed Normal rail keyboard navigation without file protocol changes.
Spec: ../specs/2026-11-14-pptx-normal-rail-navigation-design.md

## Constraints
Preserve CSS/native ol/button/Tab. Reuse original synchronous click+notes.flush; next differs from current before click, verify selected target after click. Ignore modifiers/IME/defaultPrevented/modal/nonNormal/management controls. No push/PR/merge/deploy. Do not repeat full tests.

## Review focus
- DOM rebuild: repeat keys keep focus on new button.
- Veto: selected==target must not fake success or steal error focus.
- Current order: hidden/new/noncontiguous IDs and section rows preserve identity.
- Boundaries: consume but no duplicate flush.
- No dirty notes: navigation has no draft/history/save; dirty notes retain existing flush semantics.

## Tasks
- [x] Write controller DOM tests for navigation, focus rebuild, veto, guards and dispose; run RED.
- [x] Add slides-rail-navigation.ts mountSlidesRailNavigation(list,{enabled,current,open}) controller; run GREEN.
- [x] Add real slides-main DOM integration test for focus/current/order/no-clean-draft/save plus notes flush; run RED before wiring.
- [x] Preserve original click body, wire controller and dispose, aria-current; run GREEN and relevant views/notes regressions.
- [x] Run final diff check/typecheck; independent Astra review; stage changes locally only and record exact passed/blocked checks.

## Verification limits
Full tsc default/3072MB killed; 2048MB OOM. Chromium socket permission blocked. Focused strict helper/test tsc passed; related 47 tests passed; independent Astra 12 passed; final hygiene 5 passed. Complete frontend type closure/build/budget and actual long-rail visibility are delegated to configured cloud-stage verification, not reported passing here. No remote action.
