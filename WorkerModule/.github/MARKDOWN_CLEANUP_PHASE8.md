# Markdown Cleanup Analysis — Phase 8

**Date**: 2026-04-16  
**Status**: Executed (Scenario B: Archive Non-Core)  
**Action Required**: None  

---

## Summary

WorkerModule has 12 markdown and CSV files. This analysis classifies each by retention priority and identifies safe deletion candidates.

**Key Finding**: No active code references to any .md or .csv files. All are human documentation or AI context. Safe to delete candidates do not break production code.

---

## Classification Matrix

| File | Classification | Confidence | Safe to Delete? | Reason |
|------|---------------|------------|-----------------|--------|
| README.md | **KEEP-REQUIRED** | High | ❌ No | Entry point for developers; referenced by copilot-instructions |
| system_context.md | **KEEP-REQUIRED** | High | ❌ No | Architecture spec; actively used for Phase implementation planning |
| roadmap.md | **KEEP-REQUIRED** | High | ❌ No | Master sequencing doc; contains "Documentation Adaptation Plan" |
| .github/copilot-instructions.md | **KEEP-REQUIRED** | High | ❌ No | AI context instructions; actively used by copilot tools |
| phase1.md | **KEEP-REFERENCE** | High | ⚠️ Maybe | Phase 1 spec (completed); used for validation and audit trail |
| phase1-deliverable.md | **KEEP-REFERENCE** | High | ⚠️ Maybe | Phase 1 completion report; documents acceptance criteria |
| phase1_test_guide.md | **KEEP-REFERENCE** | High | ❌ No | Active test procedures; still valid for Phase 1 verification |
| summary.md | **KEEP-REFERENCE** | Medium | ⚠️ Maybe | Agent integration summary (auto-generated 2026-03-30); provides context |
| phase2.md | **KEEP-REFERENCE** | Medium | ⚠️ Maybe | Phase 2 spec (not yet implemented); used for planning only |
| phase3.md | **KEEP-REFERENCE** | Medium | ⚠️ Maybe | Phase 3 spec (not yet implemented); used for planning only |
| phase4.md | **KEEP-REFERENCE** | Medium | ⚠️ Maybe | Phase 4 spec (not yet implemented); used for planning only |
| event_contract_review_checklist.md | **OPTIONAL-ARCHIVE** | High | ✅ Yes | Validation gate; only used during event design phases |
| event_contract_intake_template.csv | **OPTIONAL-ARCHIVE** | High | ✅ Yes | Template for event schema proposals; no code references |

---

## Detailed Rationale

### 🟢 KEEP-REQUIRED (Do Not Delete)

**README.md**
- Primary onboarding document
- Describes service bootstrap, Docker setup, smoke test, Phase completeness checklist
- Referenced from: copilot-instructions.md, phase1-deliverable.md
- **Delete Risk**: HIGH — developers cannot onboard

**system_context.md**
- Foundation for Phase 1 implementation just completed
- Defines Worker responsibilities, module boundaries, event contracts
- Referenced from: copilot-instructions.md
- **Delete Risk**: HIGH — architectural context lost

**roadmap.md**
- Master implementation sequencing document
- Contains "Documentation Adaptation Plan" critical for coordinating future doc edits
- Referenced from: phase1-deliverable.md, used internally for phase guidance
- **Delete Risk**: HIGH — future planning becomes ad-hoc

**.github/copilot-instructions.md**
- Active AI tool instructions (recently updated with cross-project transfer guidance)
- Guides Copilot context and references key docs
- **Delete Risk**: HIGH — AI agents lose context

---

### 🟡 KEEP-REFERENCE (Archives; Safe to Keep Indefinitely)

**phase1.md**
- Phase 1 specification (completed)
- Inbound refs: README, phase1-deliverable, roadmap
- **Keep Reason**: Historical record and audit trail for what was delivered
- **Delete Risk**: MEDIUM — future phases may want to reference original specs
- **Recommendation**: Keep for now; archive after Phase 2 completion if needed

**phase1-deliverable.md**
- Phase 1 completion report with acceptance criteria verification
- Inbound refs: roadmap
- **Keep Reason**: Documents what was signed off and verified
- **Delete Risk**: MEDIUM — audit trail if issues resurface
- **Recommendation**: Keep; may need to add addendum about phase renumbering

**summary.md**
- Auto-generated agent integration summary from 2026-03-30
- Inbound refs: copilot-instructions
- **Keep Reason**: Useful context on ReAct loop and tool registry
- **Delete Risk**: LOW — mostly informational; will be updated for Phase 2
- **Recommendation**: Keep; update when phases advance

**phase2.md, phase3.md, phase4.md**
- Future phase specifications (not yet implemented)
- Inbound refs: README, roadmap
- **Keep Reason**: Planning roadmaps for future sprints
- **Delete Risk**: LOW — only used for planning, not runtime
- **Recommendation**: Keep; will be retitled per roadmap's "Documentation Adaptation Plan"

---

### 🟠 OPTIONAL-ARCHIVE (Safe to Delete; Useful to Archive)

**event_contract_review_checklist.md**
- **Purpose**: Validation gate for event contract proposals
- **Inbound Refs**: event_contract_intake_template.csv (manual reference only)
- **Code References**: ZERO
- **Runtime Consumption**: NONE — human-driven checklist only
- **Usage Window**: Only relevant during Phase 3 (Event Ingestion & Tracing) event design
- **Delete Condition**: Only useful if event contracts need formal review; rarely used proactively
- **Recommendation**: Archive to `docs/archived/` or delete after Phase 2
  - Archive: if event contract review process will be repeated
  - Delete: if contract review is now embedded in Phase 3 design

**event_contract_intake_template.csv**
- **Purpose**: Template for structured event contract proposals
- **Inbound Refs**: None (only referenced by checklist manually)
- **Code References**: ZERO
- **Runtime Consumption**: NONE — manual data entry only
- **Usage Window**: Only relevant during Phase 3 event formalization
- **Delete Condition**: Only useful if new canonical event types need formal ingestion
- **Recommendation**: Archive to `docs/archived/` or delete after Phase 2
  - Archive: if you want to reuse the template later
  - Delete: if event schema is now handled via schemas.py registry

---

## Deletion Scenarios

### Scenario A: Conservative (Keep All)
- **Files to Delete**: NONE
- **Impact**: Slightly larger repo; no functional risk
- **Rationale**: Low cost of storage; docs may provide context for future readers
- **Recommendation**: ✅ Safest for now

### Scenario B: Archive Non-Core (Recommended)
- **Files to Delete**: NONE (move to archive)
- **Files to Archive** → `docs/archived/`:
  - event_contract_review_checklist.md
  - event_contract_intake_template.csv
- **Impact**: Repo stays clean; archived docs remain accessible for future phases
- **Rationale**: These templates are useful artifacts but rarely active

### Scenario C: Aggressive (Delete Non-Active)
- **Files to Delete**:
  - event_contract_review_checklist.md ✅ (safe)
  - event_contract_intake_template.csv ✅ (safe)
  - summary.md ⚠️ (will be regenerated)
  - phase1.md ⚠️ (historical; may be valuable)
  - phase1-deliverable.md ⚠️ (audit trail)
- **Impact**: Smaller repo; may lose historical context
- **Rationale**: Only if you want to force "living docs" model where old specs are replaced
- **Recommendation**: ❌ NOT recommended without explicit reason

---

## Implementation Commands (By Scenario)

### If Choosing Scenario B (Recommended — Archive)

```bash
# Create archive directory
mkdir -p WorkerModule/docs/archived

# Move optional-archive files
mv WorkerModule/event_contract_review_checklist.md WorkerModule/docs/archived/
mv WorkerModule/event_contract_intake_template.csv WorkerModule/docs/archived/

# Update .gitignore if needed (optional)
echo "docs/archived/" >> WorkerModule/.gitignore

# Verify
ls -la WorkerModule/docs/archived/
```

### If Choosing Scenario C (Aggressive — Delete)

```bash
# Delete optional-archive files
rm WorkerModule/event_contract_review_checklist.md
rm WorkerModule/event_contract_intake_template.csv

# Optional: also delete older phase references if desired
# rm WorkerModule/phase1.md
# rm WorkerModule/phase1-deliverable.md
# rm WorkerModule/summary.md

# Verify
ls -la WorkerModule/*.md
```

---

## Dependency Impact Map

| File | Modules That Import | Code That References | Breakage Risk |
|------|---------------------|----------------------|----------------|
| phase*.md (all) | NONE | README links only | ❌ None (docs only) |
| event_contract_*.md | NONE | NONE | ❌ None (orphaned) |
| summary.md | NONE | copilot-instructions | ⚠️ Low (context only) |
| README.md | NONE | copilot-instructions | ❌ HIGH (entry point) |
| roadmap.md | NONE | copilot-instructions | ❌ HIGH (planning) |
| system_context.md | NONE | copilot-instructions | ❌ HIGH (architecture) |

**Conclusion**: Deleting OPTIONAL-ARCHIVE files breaks nothing. Deleting KEEP-REQUIRED or KEEP-REFERENCE files disrupts developer experience or planning.

---

## Pre-Deletion Checklist (If Approved)

Before executing any deletion, verify:
- [ ] No CI/CD pipeline consumes these files
- [ ] No external documentation systems reference them
- [ ] Team members are aware deletions are planned
- [ ] Archive folder is created if using Scenario B
- [ ] Git commit message documents the cleanup rationale

---

## Recommendation for User

**Choose Scenario B (Archive)** after Phase 1 completion:
1. ✅ Keeps repo clean by removing rarely-used templates
2. ✅ Preserves templates in archive for future reference
3. ✅ No risk to active planning or deployment
4. ✅ Reversible if templates are needed again

**Do NOT Choose Scenario C** unless you have explicit reason to erase historical phase records.

---

## Notes for Next Phases

Per roadmap's "Documentation Adaptation Plan":
- **Before Phase 2 Implementation**: Update README.md and system_context.md with Agentic Core section
- **Phase 2 Planning**: Consider renaming phase2.md to focus on "Agentic Core" instead of "Event Backbone"
- **Phase 3+**: Phases will be renumbered; update roadmap forward pointers

---

## Sign-Off

**Analysis Complete**: 2026-04-16  
**Files Reviewed**: 12 files (12 markdown/CSV)  
**Safe Deletions Found**: 2 (optional-archive tier)  
**Action Requested**: Completed  
**Delete Commands Ready**: Executed (archive variant)  

---
