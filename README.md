# aisubtranslator

Translate subtitles with an LLM. Drop in a subtitle file or a video, get a
sidecar your player picks up automatically.

Built for watching things: the goal is a translation good enough that you stop
noticing you are reading one. Tuned for English into Danish, works for any pair.

```bash
export OPENROUTER_API_KEY=sk-or-...

aisubtranslator translate Some.Film.2019.mkv --to da
# → Some.Film.2019.da.srt, beside the video
```

## What it does

- Takes a **subtitle file** (`.srt`, `.ass`, `.ssa`, `.vtt`) or a **video**, and
  pulls the text subtitles out of the video itself.
- Picks the right track when a release ships four of them — full dialogue,
  forced, SDH, signs & songs — and asks you only when the call is genuinely
  close.
- Builds a **reference sheet** for the film or series so character names and
  recurring terms stay consistent, including across episodes.
- Translates in chunks with surrounding context, so a sentence spanning several
  cues is translated as a sentence.
- **Never changes timings or cue structure.** Nothing is merged, split, dropped
  or reordered, which is what stops subtitles drifting out of sync.
- Keeps ASS styling, positioning and typesetting intact.
- Re-breaks lines for Danish rather than mirroring where English broke them.
- Resumes where it stopped if a run dies.

## What it deliberately does not do

- **Image-based subtitles** (Blu-ray PGS, DVD VobSub). These are pictures of
  text and would need OCR. It tells you that is what it found.
- **Transcription from audio.** If there are no subtitles, there is nothing to
  translate. The architecture leaves room for this; it is not built.
- **Muxing back into the container.** Output is a sidecar; your original video
  is never touched.
- No GUI.

## Commands

```bash
# Translate. Refuses to overwrite unless told to.
aisubtranslator translate FILE --to da [--from en] [-o OUT] [--track N] [--overwrite]

# See what subtitle tracks a video has, and which one would be chosen.
aisubtranslator tracks Some.Film.2019.mkv

# Translate a handful of cues and print them side by side, to judge quality
# before committing to a whole file. This one makes a real request.
aisubtranslator sample Some.Film.2019.mkv -n 20

# Your target-language conventions. Edit once, applies everywhere.
aisubtranslator style --init

# The reference sheet for the film or series in a folder.
aisubtranslator bible Some.Film.2019.mkv
```

`subtl` works as a shorter alias for all of the above.

## Concepts

A **Work** is a directory. The folder holding your media *is* the film or the
season, which is why there is no title parsing and no identity database, and why
episode 7 automatically inherits the terminology settled in episode 1. Its
reference sheet — the **Bible** — lives in `.aisubtranslator/bible.toml` inside
that folder.

The Bible is meant to be edited. Correct a name there and it holds for
everything translated afterwards; freshly derived entries never overwrite what
is already written down. Editing it invalidates the resume checkpoint, so the
correction actually takes effect.

**Style Preferences** are separate, and describe the *output* rather than the
input: formality, whether profanity is softened, how idioms are handled. Defaults
are modern Danish, `du`-form, profanity preserved at source intensity. They live
at `~/.config/aisubtranslator/style.toml`, and a Work can override them with its
own `style.toml`.

Full glossary in [CONTEXT.md](CONTEXT.md). Decisions worth understanding before
changing them are in [docs/adr/](docs/adr/).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | *(required)* | Your key. Never written to disk. |
| `AISUBTRANSLATOR_MODEL` | `anthropic/claude-sonnet-4.5` | Any OpenRouter model id. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Override the endpoint. |

Routing is pinned to a single upstream by default, so schema strictness and
prompt-cache hits stay consistent for a whole job — see
[ADR 0003](docs/adr/0003-openrouter-routing-is-pinned.md). Pass
`--no-pin-routing` to widen it if a model is unavailable.

## When something goes wrong

Anything less than perfect goes into a **run report** written beside the output
— cues passed through untranslated, cues where translation failed, cues that
became harder to read — each with its timecode so you can jump straight to it.
The subtitle file itself stays clean: no markers, nothing on screen that was not
meant to be read.

Reading speed is reported comparatively, not absolutely. Source subtitles are
frequently over budget already — a real episode of Arrow had 228 of 535 source
cues above 17 chars/sec — so listing every one of those tells you nothing about
the translation. The report gives the total as a single line, then lists only
the cues the translation made *worse than the source*: any cue pushed over the
line from a comfortable start, and any already-fast cue made clearly worse.

A failed cue keeps its source text rather than going blank. A dead provider
leaves a complete, untranslated file and a report explaining why, not a crash.

Rerunning after any interruption resumes from the last completed chunk.

## Development

```bash
uv sync
uv run pytest              # offline, deterministic, no API key needed
uv run pytest --cov
```

Every automated test runs against fake providers, including adversarial ones
that drop, duplicate, reorder and merge lines the way real models do. The
anchor test loads a real ASS file, runs the full pipeline with an identity
provider, and asserts the result is structurally identical to the input —
timings, styles, layers, margins, embedded fonts and all.

Container handling is tested against a real MKV built with ffmpeg at test time,
and skipped if ffmpeg is absent.

`aisubtranslator sample` is the only thing that makes a real request.

Requires ffmpeg on `PATH` for video input. Subtitle files need nothing.
