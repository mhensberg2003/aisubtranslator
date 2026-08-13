# Context

Domain glossary for the AI subtitle translator. Terms here are the project's
ubiquitous language — code, prompts, docs and CLI output should use these words
and no synonyms.

## Media

### Work
A body of related media that shares terminology — a film, or a series. A Work
**is a directory**: the folder containing the media files. This is definitional,
not a heuristic, which is why the project never has to parse titles out of
release filenames or maintain an identity registry. A Work owns a Bible.

### Subtitle Track
A time-ordered sequence of Cues in a single language. A Track arrives either as
a **sidecar** file beside the media, or as a **stream** inside a video
container.

A single video commonly carries several Tracks in the same language which are
*not* interchangeable: a full dialogue Track, a **forced** Track (foreign
dialogue only), a **hearing-impaired** Track (dialogue plus sound annotations
and speaker labels), and a **signs** Track (on-screen text only). Choosing
between them is a real decision, not a formality.

### Extraction
Obtaining a Subtitle Track from a video container. Succeeds only for **text**
Tracks. Image-based Tracks (Blu-ray, DVD) and media carrying no Track at all
are out of scope, and are reported as such rather than guessed at.

## Subtitle structure

### Cue
One timed unit of subtitle: a start time, an end time, and a Payload — plus
whatever presentation fields its format carries (style, layer, margins, effect).

A Cue's **timing and identity are immutable** through translation. Cues are
never merged, split, dropped, or reordered. Only the Payload changes.

### Payload
The translatable text of a Cue — what a viewer reads and what carries meaning.
Distinct from the Cue's raw text, which also contains markup the viewer never
sees.

Not every Cue has a translatable Payload. Invisible authoring events, lines
whose timing subdivides syllables for karaoke, and cues containing no letters
are **passed through verbatim**. A Cue passed through is always recorded with
its reason; nothing is dropped silently.

### Override Tag
Inline markup embedded inside a Payload that controls presentation rather than
meaning — italics, positioning, karaoke timing. Override Tags are not
translatable content and must survive translation unchanged.

### Reading Budget
The characters a viewer can comfortably read in a Cue's display duration.
Translations that exceed it are still emitted — never truncated.

Exceeding the budget is not by itself a defect. Source subtitles routinely
exceed it, because fast dialogue is written that way, and reporting inherited
pacing back buries the Cues actually worth looking at. So the Run Report
distinguishes the two: it summarises how many Cues are over budget, and lists
only those the translation made **harder to read than the source already was**.

## Translation

### Source Language
The language of the incoming Track. Detected, not assumed.

### Target Language
The language the viewer wants to read. Chosen per run.

### Bible
The reference sheet derived from a whole Track before any translation happens:
character names, recurring terminology, register and formality, genre and tone.
The Bible is what keeps terminology consistent across a feature-length Track
instead of drifting between requests.

A Bible belongs to a Work and persists. Later episodes load it, use it, and
extend it. It is human-readable and human-editable: correcting a rendering in
the Bible fixes it for everything translated afterwards.

### Style Preferences
The conventions **declared** for the Target Language — formality, whether
profanity is preserved at equivalent intensity, how idioms are handled, whether
units and proper nouns are left alone.

Distinct from the register **observed** in the source, which is the Bible's job.
The Bible describes what the source is; Style Preferences describe what the
output should be.

### Chunk
A contiguous run of Cues submitted for translation as one unit.

### Context Cue
A Cue supplied alongside a Chunk for continuity, read-only. Context Cues let the
translator see a sentence that spans a Chunk boundary. They are never translated
as part of that Chunk.

### Alignment
The invariant that the set of Cue identities coming back from a translation
request is exactly the set that went in. A break in Alignment is the failure
mode that desynchronises every subsequent Cue, so it is checked on every
response, never assumed.

### Repair
The bounded recovery cycle following an Alignment break: re-request only the
affected Cues, then translate them individually, and finally — rather than
failing the whole Track — keep the source text and record it. Repair is what
makes Alignment a checked invariant instead of a hope.

## Running

### Job
One resumable execution over one Track. A Job records which Chunks are complete,
so an interrupted run resumes rather than restarts and never re-pays for
completed work.

### Run Report
The record of everything that degraded during a Job: Cues passed through, Cues
that exhausted Repair, translations that became harder to read than the source,
and what was spent.
The Run Report exists so the translated Track itself can stay clean — no
markers, no annotations, nothing on screen that wasn't meant to be read.
