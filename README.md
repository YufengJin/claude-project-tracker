# project-tracker

[中文说明](README_zh.md)

A Claude Code / Codex plugin that keeps a **resumable, auditable archive** for work that spans many
sessions. The archive lives inside the repo you are working on, under `.claude/project/<slug>/`:

| File | Role | Mutability |
|---|---|---|
| `charter.md` | goal, done-criteria, out-of-scope, constraints, how to verify | written once, rarely changed |
| `plan.md` | how you intend to get there | snapshot, rewritten freely |
| `state.md` | where you are now, dead ends, quick-start commands | snapshot, ≤ 100 lines |
| `journal.md` | one entry per session with evidence | **append-only** |
| `decisions.md` | architecture decision records (ADR) | **append-only** |

A fresh session with zero context reads the archive and resumes from a five-line brief. Every result,
dead end and decision is checkpointed with evidence, so nothing that git cannot record is lost:
intent, assumptions, failed attempts, the user's own words.

One skill, four modes: `new` / `resume` / `checkpoint` / `list`.

## Install

### Claude Code

```bash
claude plugin marketplace add YufengJin/claude-project-tracker
claude plugin install project-tracker@project-tracker
```

For local development point at the plugin directory directly:

```bash
claude --plugin-dir /path/to/claude-project-tracker/plugins/project-tracker
```

The plugin ships two hooks (`hooks/hooks.json`):

- `SessionStart` (startup / resume / compact) runs `brief.sh --if-active` and injects the brief of the
  `ACTIVE` project into context. Silent when the repo has no `.claude/project/ACTIVE`.
- `PreCompact` reminds the model to checkpoint before context is compacted.

### Codex CLI

```bash
codex plugin marketplace add YufengJin/claude-project-tracker   # or a local clone path
codex plugin add project-tracker@project-tracker
```

Or symlink the skill into the user skill directory:

```bash
ln -s /path/to/claude-project-tracker/plugins/project-tracker/skills/project-tracker ~/.codex/skills/project-tracker
```

Codex has no SessionStart hook; on resume the skill runs `scripts/brief.sh` itself.

## How to use

You normally do not name the skill. Natural phrasing triggers it, in Chinese or English.

### Start a project

> "Start a project: migrate the config parser from argparse to click."
> "立一个项目：把 config 解析从 argparse 迁到 click。"

The skill first reads `INDEX.md` (the name might be an alias of an existing project), then asks four
charter questions **in one batch**:

1. What does "done" look like? Needs a decidable criterion (`p99 < 200ms`, not "faster").
2. What is explicitly out of scope?
3. Known constraints? (interfaces that must not change, deadlines, compatible versions)
4. How will it be verified? (test command, reference implementation, baseline numbers)

Anything you cannot answer is written as `待定` / TBD under *Open questions*, never guessed. Then it
creates the five files, adds a row to `INDEX.md`, writes the slug into `ACTIVE`, and records the first
journal entry. You can also give all four answers up front in the same message.

### Resume

> "Continue auth-refactor, where were we?"
> "继续 auth-refactor，我们做到哪了？"

The skill runs `scripts/brief.sh <slug>`, which prints exactly what a cold start needs in the right
order and amount: the INDEX row, `charter.md`, `state.md`, the **last three** journal entries, the ADR
titles, `plan.md`. Then you get at most five lines: where we are, what happened last time, next step,
what is blocked, what needs your decision. No file dumps. Then it starts working.

### Checkpoint

> "Save progress." / "That's it for today." / "记一下" / "存档"

The skill also **proposes** a checkpoint on its own when a plan step finishes, a done-criterion turns
green, a dead end is found, or before `/compact`. Files are written in order of what cannot be rebuilt:

1. append a `journal.md` entry, whose `Result` carries evidence (the command, the output, failed→passed)
2. rewrite `state.md`, promoting failed attempts from the journal into *别再试 / do not retry*
3. update `plan.md` if it changed
4. append an ADR to `decisions.md` if an architecture-level choice was made
5. update the status and date in `INDEX.md`

A done-criterion is ticked only when a journal entry provides the evidence. One session writes exactly
one journal entry; a second checkpoint in the same session rewrites that entry.

### List

> "Which projects are there?" / "有哪些项目？"

Reads `INDEX.md` and lists slug, name, status, last update. No expansion, no writes.

### Explicit invocation

```
/project-tracker new <slug>          # Claude Code
/project-tracker resume <slug>
/project-tracker checkpoint
/project-tracker list

codex '$project-tracker resume <slug>'   # Codex
```

`brief.sh` also works standalone from the repo root:

```bash
bash ~/.claude/plugins/cache/project-tracker/project-tracker/0.1.0/skills/project-tracker/scripts/brief.sh <slug>
bash .../brief.sh list          # print INDEX.md
bash .../brief.sh --if-active   # brief of ACTIVE, silent if none (what the hook runs)
```

### Making it stick

Skill triggering is probabilistic. Three layers make the workflow reliable, and any one of them failing
is covered by the other two:

- the hooks above inject state deterministically on every session start
- a paragraph in the project's `CLAUDE.md` / `AGENTS.md` makes the rules hard:

  ```markdown
  ## Project archive
  State lives in .claude/project/<slug>/. At session start read charter, state and the last 3 journal
  entries; after any result append the journal and rewrite state; append decisions for architecture choices.
  ```

- the skill itself carries the details and templates (`reference/templates.md`)

Commit `.claude/project/` to git so the archive travels with the repo and every checkpoint is diffable.

### When not to use it

A task that finishes within one day and one session: `--continue` and a todo list are enough. Several
people or agents writing the same project concurrently: use an issue tracker, markdown will conflict.

## Layout

```
.claude-plugin/marketplace.json        the repo root is the marketplace (Claude Code)
.agents/plugins/marketplace.json       Codex registration
plugins/project-tracker/
  .claude-plugin/plugin.json
  .codex-plugin/plugin.json
  skills/project-tracker/              the single source of truth
    SKILL.md
    reference/templates.md             templates for the five files, INDEX and ACTIVE
    reference/hooks.md                 hook notes and an optional Stop gate
    scripts/brief.sh                   prints a project brief in recovery order
  .agents/skills -> ../skills          Codex / OpenCode / OpenHands
  .claude/skills -> ../skills          Claude Code project scope
  hooks/hooks.json                     Claude Code SessionStart / PreCompact
tests/                                 fixture repo with a seeded archive + cross-model runner
```

## Testing

`tests/` holds a fixture repository with a pre-seeded archive and a runner that drives the four modes
(list / resume / checkpoint / new) non-interactively through Claude Code (opus, fable) and Codex,
then checks triggering, write order and the append-only invariants. See [tests/README.md](tests/README.md).

## License

MIT.
