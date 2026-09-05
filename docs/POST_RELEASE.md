# Post-release cleanup

Stable `v2.1.6` has already been published as an immutable release and passed its tagged deployment smoke test. The version-specific automatic publisher used to create that release is therefore intentionally retired after publication.

This prevents unrelated post-release commits to `main` from repeatedly running a historical `Publish v2.1.6 release` job and rerunning release-only validation for a tag that already exists.

Historical release scripts and evidence remain version-controlled. The next release PR must add or update an explicit publishing path for its own version and must target the exact trusted `main` SHA that passed the required release gates.
