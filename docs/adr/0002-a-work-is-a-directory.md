# A Work is a directory

Terminology must stay consistent across a season, so a Bible has to outlive a
single file — which means the project needs to know that two episodes belong to
the same Work. The obvious approach is a central store keyed by a title parsed
out of the filename, but parsing titles from release names is notoriously
unreliable, and every mismatch either splits one Work in two or merges two into
one, silently. So we define a Work as the directory containing the media, and
store its Bible inside that directory.

## Consequences

Work identity stops being a problem to solve. There is no title parser, no
matching heuristic, no confirmation prompt, and no identity database that can
drift out of sync with the filesystem. The Bible is also exactly where you would
look for it, and it travels when you move or copy the folder.

The price is a dot-directory inside the media library, and the fact that a Work
spread across several folders is two Works. Both were judged clearly cheaper
than unreliable title matching.

Read-only media locations are not supported for Bible persistence. If that
becomes a real constraint, the fix is an explicit override, not a return to
inferred identity.
