# hearth packaging

- **PKGBUILD** — real AUR-style build for `hearth-music` on the git-tag flow (python-build → python-installer); checksums are `SKIP` placeholders until the first v0.7.0 tag tarball exists.
- **com.qtjg.hearth.yml** — draft winget manifest (single-file style, `qtjg.hearth`); installer URL + sha256 + SilentSwitch values are placeholders for the future GitHub-release `.exe`.
- **hearth.rb** — draft Homebrew cask skeleton (`cask "hearth"`, `livecheck strategy :github_releases`); dmg URL and digest are placeholders.
- **arch/PKGBUILD** — older `hearth-player` draft (v0.5.0 naming), superseded by the top-level PKGBUILD but kept for reference.
- All three current manifests parse-sane and are asserted by `tests/test_ambient_misc.py`; none is submitted upstream yet.
