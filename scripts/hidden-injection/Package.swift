// swift-tools-version:5.9
// SwiftPM manifest for the OCR helper (ocr.swift) of the hidden-injection bench.
// It lets `swift build --package-path scripts/hidden-injection` build the helper,
// which is also how CodeQL's Swift autobuild finds and compiles it.
import PackageDescription

let package = Package(
  name: "hidden-injection-ocr",
  platforms: [.macOS(.v13)],
  targets: [
    .executableTarget(
      name: "ocr",
      path: ".",
      exclude: ["bench.py", "gen_images.py", "readers.mjs", "visible_text.js"],
      sources: ["ocr.swift"]
    )
  ]
)
