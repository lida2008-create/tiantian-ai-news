import AVFoundation
import Foundation

if CommandLine.arguments.count < 3 {
    fputs("Usage: swift macos_tts.swift <input.txt> <output.caf> [voice] [rate]\n", stderr)
    exit(1)
}

let inputPath = CommandLine.arguments[1]
let outputPath = CommandLine.arguments[2]
let voiceName = CommandLine.arguments.count > 3 ? CommandLine.arguments[3] : "Tingting"
let rateValue = CommandLine.arguments.count > 4 ? Float(CommandLine.arguments[4]) ?? 0.42 : 0.42

let text = try String(contentsOfFile: inputPath, encoding: .utf8)
let outputURL = URL(fileURLWithPath: outputPath)
try? FileManager.default.removeItem(at: outputURL)

let utterance = AVSpeechUtterance(string: text)
utterance.rate = rateValue

if let matchedVoice = AVSpeechSynthesisVoice.speechVoices().first(where: { $0.name == voiceName }) {
    utterance.voice = matchedVoice
} else {
    utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
}

let synthesizer = AVSpeechSynthesizer()
var audioFile: AVAudioFile?
var writeError: Error?
var hasAudio = false
var isFinished = false

synthesizer.write(utterance) { buffer in
    guard let pcmBuffer = buffer as? AVAudioPCMBuffer else {
        return
    }

    if pcmBuffer.frameLength == 0 {
        isFinished = true
        return
    }

    hasAudio = true

    do {
        if audioFile == nil {
            audioFile = try AVAudioFile(
                forWriting: outputURL,
                settings: pcmBuffer.format.settings,
                commonFormat: pcmBuffer.format.commonFormat,
                interleaved: pcmBuffer.format.isInterleaved
            )
        }
        try audioFile?.write(from: pcmBuffer)
    } catch {
        writeError = error
        isFinished = true
    }
}

let deadline = Date().addingTimeInterval(300)
while !isFinished && Date() < deadline {
    RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
}

if let writeError {
    fputs("Audio write failed: \(writeError)\n", stderr)
    exit(1)
}

if !isFinished {
    fputs("Timed out waiting for synthesized audio.\n", stderr)
    exit(1)
}

if !hasAudio {
    fputs("No audio frames were produced.\n", stderr)
    exit(1)
}
