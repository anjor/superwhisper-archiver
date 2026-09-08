// swhelper — the bits of the auto-capture trigger that Python cannot reach.
//
// `mic` answers "which apps are capturing audio input right now", which the
// callwatch reconciler uses for both halves of its loop: whether a call is
// happening, and whether superwhisper is actually recording it.
//
// `toggle` presses superwhisper's record hotkey. It exists because the URL
// scheme cannot stop a recording: probed on 2.17.3, superwhisper://stop and
// superwhisper://cancel both leave the mic held and the recording running.
//
// The CoreAudio process API (kAudioHardwarePropertyProcessObjectList, macOS 14+)
// is C with no Python binding, and CGEvent posting needs the same native
// access, hence Swift — and one binary, so Accessibility is granted once.

import ApplicationServices
import CoreAudio
import CoreGraphics
import Darwin
import Foundation

// MARK: - CoreAudio property helpers

private func address(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
}

/// Every process CoreAudio knows about, whether or not it is running audio.
func audioProcessObjectIDs() throws -> [AudioObjectID] {
    var addr = address(kAudioHardwarePropertyProcessObjectList)
    var dataSize: UInt32 = 0
    var status = AudioObjectGetPropertyDataSize(
        AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &dataSize)
    guard status == noErr else { throw SWError.coreAudio("process list size", status) }

    let count = Int(dataSize) / MemoryLayout<AudioObjectID>.size
    guard count > 0 else { return [] }

    var ids = [AudioObjectID](repeating: 0, count: count)
    status = AudioObjectGetPropertyData(
        AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &dataSize, &ids)
    guard status == noErr else { throw SWError.coreAudio("process list", status) }
    return ids
}

private func boolProperty(_ objectID: AudioObjectID, _ selector: AudioObjectPropertySelector) -> Bool {
    var addr = address(selector)
    var value: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    let status = AudioObjectGetPropertyData(objectID, &addr, 0, nil, &size, &value)
    return status == noErr && value != 0
}

private func stringProperty(_ objectID: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
    var addr = address(selector)
    var value: CFString? = nil
    var size = UInt32(MemoryLayout<CFString?>.size)
    let status = withUnsafeMutablePointer(to: &value) { pointer in
        AudioObjectGetPropertyData(objectID, &addr, 0, nil, &size, pointer)
    }
    guard status == noErr, let string = value as String?, !string.isEmpty else { return nil }
    return string
}

private func pidProperty(_ objectID: AudioObjectID) -> pid_t? {
    var addr = address(kAudioProcessPropertyPID)
    var value: pid_t = -1
    var size = UInt32(MemoryLayout<pid_t>.size)
    let status = AudioObjectGetPropertyData(objectID, &addr, 0, nil, &size, &value)
    guard status == noErr, value > 0 else { return nil }
    return value
}

// MARK: - Model

struct AudioProcess: Encodable {
    let objectID: UInt32
    let pid: Int32?
    let bundleID: String?
    let name: String?
    let runningInput: Bool
    let runningOutput: Bool
}

enum SWError: Error, CustomStringConvertible {
    case coreAudio(String, OSStatus)
    case usage(String)
    case notTrusted

    var description: String {
        switch self {
        case let .coreAudio(what, status):
            return "CoreAudio \(what) failed with status \(status)"
        case let .usage(message):
            return message
        case .notTrusted:
            return """
                not trusted for Accessibility, so key events cannot be posted.
                Grant it in System Settings > Privacy & Security > Accessibility.
                """
        }
    }
}

/// A process with no bundle ID still has a name worth reporting — a mic holder
/// we cannot identify is more useful in the log than a null. libproc rather than
/// NSRunningApplication so this stays a Foundation-only tool and can also name
/// daemons, which are not applications.
private func processName(_ pid: pid_t?) -> String? {
    guard let pid else { return nil }
    // PROC_PIDPATHINFO_MAXSIZE (4 * MAXPATHLEN); the macro does not survive the
    // Swift importer, so it is spelled out.
    var buffer = [CChar](repeating: 0, count: 4 * 1024)
    guard proc_pidpath(pid, &buffer, UInt32(buffer.count)) > 0 else { return nil }
    let path = String(cString: buffer)
    guard !path.isEmpty else { return nil }
    return (path as NSString).lastPathComponent
}

func snapshot() throws -> [AudioProcess] {
    try audioProcessObjectIDs().map { objectID in
        let pid = pidProperty(objectID)
        return AudioProcess(
            objectID: objectID,
            pid: pid,
            bundleID: stringProperty(objectID, kAudioProcessPropertyBundleID),
            name: processName(pid),
            runningInput: boolProperty(objectID, kAudioProcessPropertyIsRunningInput),
            runningOutput: boolProperty(objectID, kAudioProcessPropertyIsRunningOutput)
        )
    }
}

// MARK: - Output

private func emit<T: Encodable>(_ value: T) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    let data = try encoder.encode(value)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

// MARK: - Subcommands

/// Bundle IDs holding the microphone, as a JSON array. This is the reconciler's
/// only input, so its shape is deliberately boring.
func runMic(detail: Bool) throws {
    let processes = try snapshot()
    if detail {
        try emit(processes.sorted { $0.objectID < $1.objectID })
        return
    }
    let holders = processes
        .filter(\.runningInput)
        .compactMap { $0.bundleID ?? $0.name }
    try emit(Array(Set(holders)).sorted())
}

/// superwhisper's toggleRecording shortcut, read from its own preferences so a
/// rebind does not silently break the daemon. Carbon modifier bits, as stored by
/// the KeyboardShortcuts library.
struct Hotkey {
    var keyCode: CGKeyCode
    var flags: CGEventFlags

    /// ⌥Space, superwhisper's default.
    static let fallback = Hotkey(keyCode: 49, flags: .maskAlternate)

    static func fromPreferences() -> Hotkey {
        let carbonCmd = 256, carbonShift = 512, carbonOption = 2048, carbonControl = 4096
        guard
            let raw = UserDefaults(suiteName: "com.superduper.superwhisper")?
                .string(forKey: "KeyboardShortcuts_toggleRecording"),
            let object = try? JSONSerialization.jsonObject(with: Data(raw.utf8)),
            let dictionary = object as? [String: Any],
            let code = dictionary["carbonKeyCode"] as? Int
        else { return .fallback }

        let modifiers = dictionary["carbonModifiers"] as? Int ?? 0
        var flags: CGEventFlags = []
        if modifiers & carbonCmd != 0 { flags.insert(.maskCommand) }
        if modifiers & carbonShift != 0 { flags.insert(.maskShift) }
        if modifiers & carbonOption != 0 { flags.insert(.maskAlternate) }
        if modifiers & carbonControl != 0 { flags.insert(.maskControl) }
        return Hotkey(keyCode: CGKeyCode(code), flags: flags)
    }
}

struct ToggleResult: Encodable {
    let sent: Bool
    let hotkey: String
    let trusted: Bool
}

/// Press superwhisper's record hotkey.
///
/// Toggling is blind — it starts if stopped and stops if started — so the
/// reconciler must check `mic` before and after rather than trusting this.
func runToggle(dryRun: Bool) throws {
    let hotkey = Hotkey.fromPreferences()
    let description = "keyCode \(hotkey.keyCode) flags \(hotkey.flags.rawValue)"

    guard AXIsProcessTrusted() else {
        throw SWError.notTrusted
    }
    if dryRun {
        try emit(ToggleResult(sent: false, hotkey: description, trusted: true))
        return
    }

    guard
        let source = CGEventSource(stateID: .hidSystemState),
        let down = CGEvent(keyboardEventSource: source, virtualKey: hotkey.keyCode, keyDown: true),
        let up = CGEvent(keyboardEventSource: source, virtualKey: hotkey.keyCode, keyDown: false)
    else { throw SWError.usage("could not synthesise \(description)") }

    down.flags = hotkey.flags
    up.flags = hotkey.flags
    down.post(tap: .cghidEventTap)
    usleep(30_000)
    up.post(tap: .cghidEventTap)

    try emit(ToggleResult(sent: true, hotkey: description, trusted: true))
}

let usage = """
usage: swhelper <command>

  mic             bundle IDs currently capturing audio input, as a JSON array
  mic --detail    every audio process with its pid, name and input/output state
  toggle          press superwhisper's record hotkey (needs Accessibility)
  toggle --check  report the hotkey and whether Accessibility is granted
"""

do {
    let arguments = Array(CommandLine.arguments.dropFirst())
    switch arguments.first {
    case "mic":
        let rest = arguments.dropFirst()
        let detail = rest.contains("--detail")
        guard rest.allSatisfy({ $0 == "--detail" }) else {
            throw SWError.usage("unknown option for mic: \(rest.filter { $0 != "--detail" }.joined(separator: " "))")
        }
        try runMic(detail: detail)
    case "toggle":
        let rest = arguments.dropFirst()
        let check = rest.contains("--check")
        guard rest.allSatisfy({ $0 == "--check" }) else {
            throw SWError.usage("unknown option for toggle: \(rest.filter { $0 != "--check" }.joined(separator: " "))")
        }
        try runToggle(dryRun: check)
    case "-h", "--help", .none:
        print(usage)
    case let other?:
        throw SWError.usage("unknown command: \(other)\n\n\(usage)")
    }
} catch {
    FileHandle.standardError.write(Data("swhelper: \(error)\n".utf8))
    exit(1)
}
