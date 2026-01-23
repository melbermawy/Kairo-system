# Claude Code Instructions for Kairo

> **This file is automatically read by Claude Code at the start of every session.**

## First Thing: Read Context Files

Before doing anything, read these files in order:
1. `.claude/CONTEXT.md` - Project overview, Mohamed's working style, architecture
2. `.claude/STATE.md` - Current status and what we're working on
3. `.claude/HANDOFF.md` - If resuming mid-task, this has continuation context

## Critical Rules

### Mohamed's Working Style
- **Mohamed does NOT touch code.** Don't ask him to create, edit, or run anything.
- **Mohamed does NOT navigate files.** Don't ask him to open or check anything.
- **You do all the work.** Reading files, writing code, running commands - all you.
- **Long sessions, complete features.** Match his 10x engineer energy.

### The Two Repositories
**Never forget: Kairo is a two-repo application.**

| Repo | Path | Framework |
|------|------|-----------|
| Backend | `/Users/mohamed/Documents/Kairo-system` | Django 5.0 |
| Frontend | `/Users/mohamed/Documents/kairo-frontend/ui/` | Next.js 16 |

Most features require changes to BOTH repos.

### Quality Standards
- Do it right the first time. No "we can improve this later."
- Be proactive. Obvious next steps don't need permission.
- Test your work before saying it's done.

## Quick Reference

**Current work:** See `/docs/deployment_prep_plan.md`

**Key backend paths:**
- Source Activation: `kairo/sourceactivation/`
- Opportunity Synthesis: `kairo/hero/synthesis/`
- Background Jobs: `kairo/hero/jobs/`

**Key frontend paths:**
- Today Board: `ui/src/app/brands/[brandId]/today/`
- Onboarding: `ui/src/app/brands/[brandId]/onboarding/`
- API Client: `ui/src/lib/api/`

## When Context Gets Full

Before it compacts, update `.claude/HANDOFF.md` with:
- What you accomplished
- Where you stopped
- Immediate next actions
- Any context that might get lost
