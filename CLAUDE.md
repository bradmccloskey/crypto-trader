# Orchestrator Integration

You are running as a managed session under the Project Orchestrator.
Follow these rules for autonomous operation:

## Autonomous Work
- Work independently without asking for confirmation on routine tasks
- Follow existing .planning/STATE.md and ROADMAP.md for what to do next
- Make commits as you complete work
- Update .planning/STATE.md when you complete phases or milestones

## When You Need Human Input
If you encounter something that TRULY requires human decision-making (not routine coding):
- Architecture decisions with major trade-offs
- Ambiguous requirements where you could go multiple valid directions
- External service credentials or access you don't have
- A blocker you cannot work around

Write this file and then STOP:
```
// .orchestrator/needs-input.json
{
  "question": "Clear, specific question for the human",
  "context": "Brief context about what you were doing",
  "options": ["Option A", "Option B"],  // optional
  "timestamp": "<ISO timestamp>"
}
```

## When You Complete Work
When you finish all planned work for the current phase or milestone:
```
// .orchestrator/completed.json
{
  "summary": "What was accomplished",
  "phase": "Phase name/number completed",
  "nextSteps": "What should happen next",
  "timestamp": "<ISO timestamp>"
}
```

## When You Hit an Error
If you encounter an unrecoverable error after multiple attempts:
```
// .orchestrator/error.json
{
  "error": "Description of the error",
  "context": "What you were trying to do",
  "attempts": "What you tried",
  "timestamp": "<ISO timestamp>"
}
```

## Important
- Do NOT write signal files for routine questions you can answer yourself
- Do NOT stop working just because one task failed - move to the next task if possible
- DO update .planning/STATE.md as you work so the orchestrator can track progress
- The human will respond via the orchestrator when they see your signal