# Cue structure is immutable through translation

A translator working cue-by-cue produces bad prose, so we give the model whole
Chunks with surrounding context — which also gives it the opportunity to merge
two Cues into one, split one into two, or quietly drop a line it thought was
redundant. Any of those desynchronises every subsequent Cue in the file, and the
damage is invisible until you are twenty minutes into watching. We therefore
treat timing and Cue identity as immutable: the model returns text keyed by Cue
id and nothing else, and Alignment is validated on every single response.

## Consequences

We give up the translations that genuinely want to re-pace across Cue
boundaries — a sentence awkwardly split in the source stays awkwardly split.
That is a real quality cost, accepted knowingly, because a slightly clumsy line
is recoverable by reading and a desynchronised file is not.

It also means every response needs validation and a Repair path, rather than
being trusted. That machinery is not optional overhead; it is the thing that
makes the invariant real rather than aspirational.
