# DRAFT Homebrew cask skeleton — not yet on homebrew/cask. The dmg URL
# and sha256 are placeholders until the first GitHub release artifact
# exists; livecheck is real and will track tags the moment they land.
cask "hearth" do
  version "0.6.3"
  sha256 :no_check  # placeholder — pin a real digest at release time

  url "https://github.com/qtjg/hearth/releases/download/v#{version}/Hearth-#{version}.dmg"
  name "Hearth"
  desc "Cozy floating YouTube Music companion for every desktop"
  homepage "https://github.com/qtjg/hearth"

  livecheck do
    url :stable
    strategy :github_releases
  end

  depends_on macos: ">= :monterey"

  app "Hearth.app"

  zap trash: "~/Library/Application Support/Hearth"
end
