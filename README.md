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
├── INDEX.md                  # one row per project: slug, name, status, last update, one-liner
├── ACTIVE                    # slug of the last brief; only a tie-breaker when a dir has several projects
└── <slug>/
    ├── charter.md            # has  Workdir: /abs/path [/another/path ...]
    ├── plan.md  state.md  journal.md  decisions.md
    └── archive/
```

- `Workdir` may list several directories, so one project can span two repositories.
- A session touches exactly one `<slug>/`. `list` reads only `INDEX.md`. Other projects' files are never
  opened, quoted or summarised, even when they share a `Workdir`. Switching projects is a `resume`.
- Move an existing in-repo archive by copying `.claude/project/<slug>` into `~/.claude/project/` and
  adding a `Workdir:` line under `Slug:` in its charter.

## `pt.sh`

```bash
PT=~/.claude/plugins/cache/project-tracker/project-tracker/0.2.0/skills/project-tracker/scripts/pt.sh
bash $PT list                                  # INDEX plus each project's Workdir
bash $PT where                                 # in-progress projects that claim $PWD
bash $PT auto                                  # what the SessionStart hook runs
bash $PT brief <slug>                          # recovery-order brief, sets ACTIVE
bash $PT new <slug> "<name>" [workdir ...]     # scaffold five files from templates, INDEX row, ACTIVE
bash $PT index <slug> "<one-liner>" [status]   # update INDEX date/one-liner; status also updates charter
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
    scripts/pt.sh                      list / where / auto / brief / new / index
    reference/templates/*.md           the five files, with {{SLUG}} {{NAME}} {{DATE}} {{WORKDIR}}
    reference/writing.md               field rules and good/bad examples
    reference/hooks.md                 how the hooks isolate context; manual install
  hooks/hooks.json                     Claude Code SessionStart / PreCompact
tests/
  unit.sh                              pt.sh behaviour and isolation, no model, seconds
  run.sh / eval.sh / scenarios.sh      model-driven scenarios against a fixture repo
```

## Testing

`bash tests/unit.sh` exercises every `pt.sh` subcommand and the isolation rules against a scratch root.
`tests/run.sh <opus|fable|codex>` drives the four modes non-interactively through a fixture repository
and `tests/eval.sh` prints the evidence. See [tests/README.md](tests/README.md).

## License

MIT.
