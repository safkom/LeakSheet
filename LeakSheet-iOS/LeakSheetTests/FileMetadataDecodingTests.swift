import AVFoundation
import Foundation
import Testing

@testable import LeakSheet

struct FileMetadataDecodingTests {
    private func decode(_ json: String) throws -> FileMetadata {
        try JSONDecoder().decode(FileMetadata.self, from: Data(json.utf8))
    }

    @Test func `pillows payload with numeric channels`() throws {
        let meta = try decode("""
        {"provider": "pillows", "container": "MPEG", "codec": "MPEG 1 Layer 3",
         "codec_profile": "CBR", "bitrate": "256kbps", "sample_rate": "44100Hz",
         "lossless": false, "channels": 2, "duration": "139.8s"}
        """)
        #expect(meta.provider == "pillows")
        #expect(meta.container == "MPEG")
        #expect(meta.codec == "MPEG 1 Layer 3")
        #expect(meta.codecProfile == "CBR")
        #expect(meta.bitrate == "256kbps")
        #expect(meta.sampleRate == "44100Hz")
        #expect(meta.lossless == false)
        #expect(meta.channels == 2)
        #expect(meta.duration == "139.8s")
    }

    @Test func `channels as numeric string decodes`() throws {
        let meta = try decode(#"{"provider": "pillows", "channels": "2"}"#)
        #expect(meta.channels == 2)
    }

    @Test func `channels as non-numeric string is nil`() throws {
        let meta = try decode(#"{"provider": "pillows", "channels": "stereo"}"#)
        #expect(meta.channels == nil)
    }

    @Test func `froste payload`() throws {
        let meta = try decode("""
        {"provider": "froste", "estimated_bitrate": 256, "bitrate": "256kbps",
         "frequency_cutoff": 19.9, "quality_mismatch": false}
        """)
        #expect(meta.estimatedBitrate == 256)
        #expect(meta.frequencyCutoff == 19.9)
        #expect(meta.qualityMismatch == false)
    }

    @Test func `imgur payload`() throws {
        let meta = try decode("""
        {"provider": "imgur", "file_size": 12345, "mime_type": "audio/mpeg",
         "filename": "song.mp3"}
        """)
        #expect(meta.fileSize == 12345)
        #expect(meta.mimeType == "audio/mpeg")
        #expect(meta.filename == "song.mp3")
    }

    @Test func `empty object decodes with all fields nil`() throws {
        let meta = try decode("{}")
        #expect(meta.provider == nil)
        #expect(meta.codec == nil)
        #expect(meta.channels == nil)
        #expect(meta.lossless == nil)
    }
}

struct FileInfoRowsTests {
    private func decode(_ json: String) throws -> FileMetadata {
        try JSONDecoder().decode(FileMetadata.self, from: Data(json.utf8))
    }

    @Test func `pillows rows include formatted duration and codec profile`() throws {
        let meta = try decode("""
        {"provider": "pillows", "container": "MPEG", "codec": "MPEG 1 Layer 3",
         "codec_profile": "CBR", "bitrate": "256kbps", "sample_rate": "44100Hz",
         "lossless": false, "channels": 2, "duration": "139.8073469387755s"}
        """)
        let rows = FileInfoRows.rows(from: meta)
        let dict = Dictionary(uniqueKeysWithValues: rows.map { ($0.label, $0.value) })
        #expect(dict["Codec"] == "MPEG 1 Layer 3 (CBR)")
        #expect(dict["Duration"] == "2:19")
        #expect(dict["Lossless"] == "No")
        #expect(dict["Channels"] == "2")
    }

    @Test func `empty metadata yields no rows`() throws {
        #expect(FileInfoRows.rows(from: try decode("{}")).isEmpty)
    }

    @Test func `player format rows`() {
        let format = StreamFormatInfo(
            codec: "MP3", sampleRateHz: 44100, channels: 2,
            indicatedBitrateBps: 256_341, trackKey: "x"
        )
        let rows = FileInfoRows.rows(from: format)
        let dict = Dictionary(uniqueKeysWithValues: rows.map { ($0.label, $0.value) })
        #expect(dict["Codec"] == "MP3")
        #expect(dict["Bitrate"] == "256 kbps")
        #expect(dict["Sample Rate"] == "44100 Hz")
        #expect(dict["Channels"] == "2")
    }

    @Test func `duration passthrough for unparseable values`() {
        #expect(FileInfoRows.formatDuration("unknown") == "unknown")
        #expect(FileInfoRows.formatDuration("210.5s") == "3:30")
    }

    @Test(arguments: [
        (kAudioFormatMPEGLayer3, "MP3"),
        (kAudioFormatMPEG4AAC, "AAC"),
        (kAudioFormatFLAC, "FLAC"),
        (kAudioFormatAppleLossless, "ALAC"),
    ])
    func `codec four-cc mapping`(fourCC: AudioFormatID, expected: String) {
        #expect(AudioEngine.codecName(fourCC) == expected)
    }
}
