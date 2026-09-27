# project-tracker

[中文说明](README_zh.md)

A Claude Code / Codex plugin that keeps a **resumable, auditable archive** for work that spans many
sessions. Archives live in **one global store**, `~/.claude/project/<slug>/`, not inside the repo, so
you never hunt through repositories for them. Each project records which code directories it belongs to
(`Workdir:`), and a session only ever loads the one project that matches the directory it runs in.

| File | Role | Mutability |
|---|---|---|
| `charter.md` | goal, done-criteria, out-of-scope, constraints, verification, `Workdir` | written once, rarely changed |
| `plan.md` | how you intend to get there | snapshot, rewritten freely |
| `state.md` | where you are now, dead ends, quick-start commands | snapshot, ≤ 100 lines |
| `journal.md` | one entry per session with evidence | **append-only** |
| `decisions.md` | architecture decision records (ADR) | **append-only** |

A fresh session with zero context reads the archive and resumes from a five-line brief. Every result,
dead end and decision is checkpointed with evidence, so nothing that git cannot record is lost:
intent, assumptions, failed attempts, the user's own words.

One skill, four modes: `new` / `resume` / `checkpoint` / `list`. One script, `pt.sh`, does the
mechanical parts.

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

- `SessionStart` (startup / resume / compact) runs `pt.sh auto`. If exactly one in-progress project
  claims the current directory, its brief is injected. If several do, only their slugs are listed and
  nothing is loaded until you name one. If none does, the hook is silent.
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

Codex has no SessionStart hook; on resume the skill runs `pt.sh brief <slug>` itself.

## Storage and isolation

```
~/.claude/project/            # override with PROJECT_TRACKER_ROOT
├── INDEX.md                  # generated: slug, name, status, host, last commit, one-liner
├── ACTIVE                    # slug of the last brief; only a tie-breaker when a dir has several projects
├── FLEET                     # hub only: one ssh alias per node (private, never published)
└── <slug>/                   # a git repository; each checkpoint is one commit
    ├── charter.md            # has  Workdir: /abs/path [...]  and  Host: <hostname>
    ├── plan.md  state.md  journal.md  decisions.md
    └── archive/
```

- `Workdir` may list several directories, so one project can span two repositories. `Host` says which
  machine those paths live on; `where` / `auto` only match projects whose `Host` is this machine.
- `INDEX.md` is rebuilt from the archives (charter fields, last commit date not counting the migration commit, the first line of the
  state's one-liner section); never edit it by hand.
- A session touches exactly one `<slug>/`. `list` reads only `INDEX.md`. Other projects' files are never
  opened, quoted or summarised, even when they share a `Workdir`. Switching projects is a `resume`.
- Move an existing in-repo archive by copying `.claude/project/<slug>` into `~/.claude/project/` and
  adding a `Workdir:` line under `Slug:` in its charter.

## `pt.sh`

```bash
PT=~/.claude/plugins/cache/project-tracker/project-tracker/0.4.0/skills/project-tracker/scripts/pt.sh
bash $PT list                                  # INDEX plus each project's host and Workdir (hub: syncs first)
bash $PT where                                 # in-progress local projects that claim $PWD
bash $PT auto                                  # what the SessionStart hook runs
bash $PT brief <slug>                          # recovery-order brief, sets ACTIVE
bash $PT new <slug> "<name>" [--host H] [workdir ...]  # scaffold the archive as a git repo, ACTIVE
bash $PT index <slug> "<one-liner>" [status]   # set the one-liner/status, commit, rebuild INDEX
bash $PT migrate                               # upgrade 0.3 archives (backup first, idempotent)
bash $PT sync [-q] [alias ...]                 # hub: fast-forward sync with the nodes
bash $PT dispatch <slug> "<task>" [--wait]     # hub: run the node's own Claude on a task
bash $PT runs [slug | --wait <run>]            # hub: dispatch status
```

## How to use

You normally do not name the skill. Natural phrasing triggers it, in Chinese or English.

### Start a project

> "Start a project: migrate the config parser from argparse to click."

The skill checks `INDEX.md` (the name might be an alias of an existing project), then asks four charter
questions **in one batch**: what does done look like (decidable), what is out of scope, known
constraints, how to verify. Anything you cannot answer is written as TBD under *Open questions*, never
guessed. Then `pt.sh new` scaffolds the archive with `Workdir` set to the current directory (pass more
directories if the project spans repos) and the skill fills in charter and plan.

### Resume

> "Continue auth-refactor, where were we?"

`pt.sh brief <slug>` prints exactly what a cold start needs, in order: the INDEX row, `charter.md`,
`state.md`, the **last three** journal entries, the ADR titles, `plan.md`. You get at most five lines:
where we are, what happened last time, next step, what is blocked, what needs your decision.

### Checkpoint

> "Save progress." / "That's it for today."

The skill also **proposes** a checkpoint on its own when a plan step finishes, a done-criterion turns
green, a dead end is found, or before `/compact`. Files are written in order of what cannot be rebuilt:

1. append a `journal.md` entry whose `Result` carries evidence (command, output, failed→passed)
2. rewrite `state.md`, promoting failed attempts from the journal into *do not retry*
3. update `plan.md` if it changed
4. append an ADR to `decisions.md` if an architecture-level choice was made
5. `pt.sh index <slug> "<one-liner>" [status]`; give a status when the project is done or dropped

One session writes exactly one journal entry; a second checkpoint in the same session rewrites that entry.

### List

> "Which projects are there?"

`pt.sh list`. No project directory is opened.

### Explicit invocation

```
/project-tracker new <slug>          # Claude Code
/project-tracker resume <slug>
/project-tracker checkpoint
/project-tracker list
```

### Human-readable record (optional)

> "Put this project's progress on the hub."

The archive is written for the next agent. Only when you ask for a record people will read does the skill
write one, to a destination listed in `~/.claude/project/HUBS.md`. That file is yours and stays out of this
repo: one short section per hub (team wiki, personal site, …) saying where it lives, who can read it, and
which manual to read first. The hub's own manual decides format and publishing. Without the file the skill
asks where to write. The page's location goes into `state.md` so the next session can update it.

```markdown
## Multiple machines: one hub for the whole fleet (optional)

Projects start wherever the code is: a workstation, a GPU server, a robot. One machine, the **hub**, sees
and can take over all of them. It needs nothing on the nodes except `git` and `sshd`, and the nodes never
connect back to the hub.

```
          hub (all archives, dispatch)          ~/.claude/project/FLEET:  gpu1
          │  ssh + git, hub-initiated only                               robot-a
     ┌────┴─────┬──────────┐                                             robot-b  # often offline
    gpu1     robot-a    robot-b     each node keeps only the projects whose Host is itself
```

- **Sync is fast-forward only.** For every project the hub compares its copy with the node's: whoever
  is ahead wins. If both sides have commits the other lacks, the project is flagged **forked**; nothing
  is merged automatically, dispatch is refused, and the next agent merges it with `git merge` by meaning
  (keep both journals' entries, rewrite the state). No wall-clock time is trusted.
- Nothing half-written moves: a checkpoint is committed by `pt index`; the hub never pushes into a node
  that has uncommitted changes, changed its archive within 15 minutes, or is running a dispatch.
  Uncommitted changes idle for 30 minutes (a forgotten checkpoint, or an old plugin that never commits)
  are committed by the hub's probe.
- `pt list` and `pt brief` on the hub sync first; a systemd user timer syncs every 15 minutes so the
  last state of a node that goes offline is kept (see `reference/hooks.md`).
- **Take over** a project from the hub by simply resuming and checkpointing there; the next sync pushes
  it back. Light work: `ssh <alias>`. Long or hardware-bound work:
  `pt dispatch <slug> "<task>" --wait` runs `claude -p` in tmux on that node (bypassPermissions by
  default, `PT_DISPATCH_MODE` to change), the agent checkpoints there, and the result syncs back.
  Status, exit code and logs live in `~/.claude/project/.runs/<run>/` on the node.
- A project whose code is elsewhere: `pt new <slug> "<name>" --host <alias> /path/on/that/machine`; the
  next sync creates it on that node.
- Setup: write the node aliases (as in `~/.ssh/config`) into `~/.claude/project/FLEET`, run
  `pt migrate` on every machine once, then `pt sync`.

Known limit: anyone sharing a node's Unix account can read that node's archives and dispatch logs.

## team-wiki (whole team can read)
- Content repo: ~/team-site/src/content/notes/, one note = <topic>/index.mdx
- Read first: its AGENTS.md. Pushing main deploys.
```

### Making it stick

Skill triggering is probabilistic. Three layers cover each other: the hooks inject state
deterministically, a paragraph in the project's `CLAUDE.md` makes the rules hard, and the skill carries
the details and templates.

```markdown
## Project archive
Archives live in ~/.claude/project/<slug>/ (global). At session start read charter, state and the last 3
journal entries of the project whose Workdir contains this repo; after any result append the journal and
rewrite state; append decisions for architecture choices. Never open another project's archive.
```

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
    scripts/pt.sh                      list / where / auto / brief / new / index / migrate
    scripts/fleet.sh                   hub: sync / dispatch / runs (sourced by pt.sh)
    scripts/probe.sh                   runs on a node over ssh; needs only git
    reference/templates/*.md           the five files, with {{SLUG}} {{NAME}} {{DATE}} {{WORKDIR}} {{HOST}}
    reference/writing.md               field rules and good/bad examples
    reference/hooks.md                 how the hooks isolate context; manual install
  hooks/hooks.json                     Claude Code SessionStart / PreCompact
tests/
  unit.sh                              pt.sh behaviour and isolation, no model, seconds
  fleet.sh  fakessh  fakeclaude        multi-machine sync and dispatch against fake hosts
  run.sh / eval.sh / scenarios.sh      model-driven scenarios against a fixture repo
```

## Testing

`bash tests/unit.sh` exercises every `pt.sh` subcommand and the isolation rules against a scratch root.
`bash tests/fleet.sh` simulates a hub and three nodes (a stub `ssh` maps each alias to a local HOME, a stub
`claude` plays the dispatched agent): import, push-back, forks and their resolution, dirty and idle nodes,
a dirty hub, offline nodes, privacy, first delivery, slug clashes, dispatch success, failure and crash.
`tests/run.sh <opus|fable|codex>` drives the four modes non-interactively through a fixture repository
and `tests/eval.sh` prints the evidence. See [tests/README.md](tests/README.md).

## License

MIT.
