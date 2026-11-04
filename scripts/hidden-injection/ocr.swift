// ocr <png>... : print "<path>\t<recognised lines joined by \n escaped as \\n>" per image.
// Apple Vision text recognition (accurate level, no language correction), the
// "agent that reads pixels" reader in scripts/hidden-injection/bench.py.
// Build: xcrun swiftc -O scripts/hidden-injection/ocr.swift -o <work>/ocr
//    or: swift build -c release --package-path scripts/hidden-injection (Package.swift;
//        CodeQL's Swift autobuild uses this one)
import Foundation
import Vision

for p in CommandLine.arguments.dropFirst() {
  let req = VNRecognizeTextRequest()
  req.recognitionLevel = .accurate
  req.usesLanguageCorrection = false
  let handler = VNImageRequestHandler(url: URL(fileURLWithPath: p), options: [:])
  try? handler.perform([req])
  let lines = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
  print(p + "\t" + lines.joined(separator: "\\n"))
}
