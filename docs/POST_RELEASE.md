# Post-release state

- **Stable:** immutable `v2.1.8` remains the recommended public release.
- **Prerelease:** immutable `v2.2.0-beta.2` is the current experimental camera-speaker release at merge SHA `9d8e8f845201cf8de1223cc7d5fc31c192194a5d`.

Stable `v2.1.8` has been published as an immutable release. Its completed `Publish v2.1.8 release` workflow was intentionally retired so ordinary post-release commits cannot rerun a historical publisher.

Beta.2 was published manually after exact-SHA candidate, merge-ref, trusted `main`, physical, and tag-triggered validation. No persistent version-specific publisher was introduced, so there is no publisher workflow to retire. Historical release scripts, release notes, and validation evidence remain version-controlled.

The next release PR must add or update an explicit publishing path for its own version, bind publication to the exact trusted `main` SHA that passed the required gates, and retire any one-version publisher after successful immutable publication.
