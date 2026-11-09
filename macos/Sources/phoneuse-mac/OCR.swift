import CoreGraphics
import Foundation
import Vision

struct TextLine {
    let text: String
    /// Pixel rect inside the cropped frame, origin top-left.
    let rect: CGRect
}

enum OCR {
    static func lines(_ img: CGImage) throws -> [TextLine] {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.recognitionLanguages = ["en-US"]

        let handler = VNImageRequestHandler(cgImage: img, options: [:])
        try handler.perform([request])

        let w = CGFloat(img.width)
        let h = CGFloat(img.height)
        var out: [TextLine] = []
        for obs in request.results ?? [] {
            guard let candidate = obs.topCandidates(1).first else { continue }
            let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
            if text.isEmpty { continue }
            let bb = obs.boundingBox // normalized, origin bottom-left
            let rect = CGRect(
                x: bb.minX * w,
                y: (1 - bb.maxY) * h,
                width: bb.width * w,
                height: bb.height * h
            )
            out.append(TextLine(text: text, rect: rect))
        }
        return sortReadingOrder(out)
    }

    static func sortReadingOrder(_ lines: [TextLine]) -> [TextLine] {
        lines.sorted { a, b in
            let rowA = Int(a.rect.midY / 8)
            let rowB = Int(b.rect.midY / 8)
            if rowA != rowB { return rowA < rowB }
            return a.rect.minX < b.rect.minX
        }
    }

    /// Exact match first, then a line that contains the words.
    static func find(_ needle: String, in lines: [TextLine]) -> TextLine? {
        let q = needle.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return nil }
        if let exact = lines.first(where: { $0.text.lowercased() == q }) { return exact }
        if let contains = lines.first(where: { $0.text.lowercased().contains(q) }) { return contains }
        // Word-by-word: every word appears in the same line.
        let words = q.split(separator: " ").map(String.init)
        return lines.first { line in
            let t = line.text.lowercased()
            return words.allSatisfy { t.contains($0) }
        }
    }
}
