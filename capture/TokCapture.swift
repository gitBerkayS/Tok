import AppKit
import ApplicationServices
import Foundation

private func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
        return nil
    }
    return value
}

private func elementAttribute(_ element: AXUIElement, _ name: String) -> AXUIElement? {
    asElement(attribute(element, name))
}

private func asElement(_ value: CFTypeRef?) -> AXUIElement? {
    guard let value = value,
          CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
    return (value as! AXUIElement)
}

private struct AccessibilityNode {
    let role: String?
    let identifiers: [String]
    let parent: AXUIElement?

    init(_ element: AXUIElement) {
        let names = [kAXRoleAttribute, kAXIdentifierAttribute, "AXDOMIdentifier", kAXParentAttribute]
        var raw: CFArray?
        let result = AXUIElementCopyMultipleAttributeValues(element, names as CFArray, [], &raw)
        let values: [AnyObject]
        if result == .success, let batch = raw as? [AnyObject], batch.count == names.count {
            values = batch
        } else {
            values = names.map { attribute(element, $0) ?? NSNull() }
        }
        role = values[0] as? String
        identifiers = [values[1], values[2]].compactMap { $0 as? String }.filter { !$0.isEmpty }
        parent = asElement(values[3])
    }
}

private func urlAttribute(_ element: AXUIElement, _ name: String) -> URL? {
    let value = attribute(element, name)
    return (value as? URL) ?? (value as? String).flatMap { URL(string: $0) }
}

private func safariAddressURL(in window: AXUIElement) -> URL? {
    let children = attribute(window, kAXChildrenAttribute) as? [AXUIElement] ?? []
    guard let toolbar = children.first(where: {
        attribute($0, kAXRoleAttribute) as? String == kAXToolbarRole
    }) else { return nil }

    // Search browser chrome only. A webpage can provide its own AX identifiers.
    var pending = [toolbar]
    let deadline = ProcessInfo.processInfo.systemUptime + 0.2
    for _ in 0..<32 {
        guard ProcessInfo.processInfo.systemUptime < deadline,
              let element = pending.popLast() else { break }
        let role = attribute(element, kAXRoleAttribute) as? String
        if role == kAXTextFieldRole,
           attribute(element, kAXIdentifierAttribute) as? String == "WEB_BROWSER_ADDRESS_AND_SEARCH_FIELD" {
            return urlAttribute(element, kAXURLAttribute) ?? urlAttribute(element, kAXValueAttribute)
        }
        if role == kAXToolbarRole || role == kAXGroupRole {
            pending.append(contentsOf: attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? [])
        }
    }
    return nil
}

private struct Snapshot: Equatable {
    let source: String?
    let status: String
    let draft: String?

    init(source: String? = nil, status: String, draft: String? = nil) {
        self.source = source
        self.status = status
        self.draft = draft
    }

    static func == (lhs: Snapshot, rhs: Snapshot) -> Bool {
        guard lhs.source == rhs.source, lhs.status == rhs.status else { return false }
        switch (lhs.draft, rhs.draft) {
        case let (left?, right?): return left.utf8.elementsEqual(right.utf8)
        case (nil, nil): return true
        default: return false
        }
    }
}

private final class Collector {
    // WebKit can represent a cleared contenteditable as a newline or zero-width placeholder.
    private let emptyDraftCharacters = CharacterSet.whitespacesAndNewlines.union(
        CharacterSet(charactersIn: "\u{200B}\u{FEFF}")
    )
    private let browsers = ["com.google.Chrome": "chrome", "com.apple.Safari": "safari"]
    private let codexBundleID = "com.openai.codex"
    private let workspace = NSWorkspace.shared
    private let environment = ProcessInfo.processInfo.environment
    private let probe = CommandLine.arguments.contains("--probe")
    private let trackSubmissions = CommandLine.arguments.contains("--track-submissions")
    private let allowUnidentifiedSafariEditor = CommandLine.arguments.contains("--allow-unidentified-safari-editor")
    private let session: URLSession
    private let port: Int
    private var activeApp: NSRunningApplication?
    private var activationObserver: NSObjectProtocol?
    private var observer: AXObserver?
    private var observedComposer: AXUIElement?
    private var receivesFocusEvents = false
    private var receivesValueEvents = false
    private var watchdog: Timer?
    private var eventRead: Timer?
    private var latest = Snapshot(status: "inactive")
    private var lastSent: Snapshot?
    private var lastSentAt: TimeInterval = -.infinity
    private var sending = false
    private var backendConnected: Bool?
    private var lastProbe: String?
    private var keyTap: CFMachPort?
    private var enterCandidate: (source: String, draft: String, composer: AXUIElement, deadline: TimeInterval)?
    private var enterCheck: Timer?
    private var submissions: [(id: String, source: String, draft: String)] = []
    private var sendingSubmission = false

    init(port: Int) {
        self.port = port
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 1
        config.timeoutIntervalForResource = 2
        session = URLSession(configuration: config)
    }

    func start() {
        if !probe {
            fputs("Tok collector started. Focus a supported prompt composer to capture a draft.\n", stderr)
        }
        activationObserver = workspace.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
        ) { [weak self] _ in
            self?.appChanged()
        }
        appChanged()
        if trackSubmissions && !probe { startSubmissionTracking() }
    }

    private func appChanged() {
        clearEnterCandidate()
        eventRead?.invalidate()
        eventRead = nil
        stopObserving()
        activeApp = workspace.frontmostApplication
        lastProbe = nil
        tick()
    }

    private func startSubmissionTracking() {
        let mask = CGEventMask(1) << CGEventType.keyDown.rawValue
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap, place: .headInsertEventTap, options: .listenOnly,
            eventsOfInterest: mask, callback: { _, type, event, context in
                guard let context = context else { return Unmanaged.passUnretained(event) }
                let collector = Unmanaged<Collector>.fromOpaque(context).takeUnretainedValue()
                if type == .tapDisabledByTimeout, let tap = collector.keyTap {
                    CGEvent.tapEnable(tap: tap, enable: true)
                } else if type == .keyDown {
                    collector.handleKeyDown(event)
                }
                return Unmanaged.passUnretained(event)
            }, userInfo: Unmanaged.passUnretained(self).toOpaque()
        ), let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0) else {
            fputs("Submission tracking needs macOS Input Monitoring permission. Draft capture is still running.\n", stderr)
            return
        }
        keyTap = tap
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
    }

    private func handleKeyDown(_ event: CGEvent) {
        let key = event.getIntegerValueField(.keyboardEventKeycode)
        let modifiers: CGEventFlags = [.maskShift, .maskControl, .maskAlternate, .maskCommand, .maskSecondaryFn]
        guard (key == 36 || key == 76), event.flags.intersection(modifiers).isEmpty,
              event.getIntegerValueField(.keyboardEventAutorepeat) == 0 else {
            clearEnterCandidate()
            return
        }
        if enterCandidate != nil { return }
        guard latest.status == "ready", let source = latest.source, let draft = latest.draft,
              !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let composer = observedComposer, let app = activeApp,
              workspace.frontmostApplication?.processIdentifier == app.processIdentifier else { return }

        enterCandidate = (source, draft, composer, ProcessInfo.processInfo.systemUptime + 1.2)
        // Briefly poll after Enter in case the editor omits its clear notification.
        enterCheck = Timer.scheduledTimer(withTimeInterval: 0.12, repeats: true) { [weak self] _ in
            self?.tick()
        }
    }

    private func clearEnterCandidate() {
        enterCandidate = nil
        enterCheck?.invalidate()
        enterCheck = nil
    }

    private func checkSubmission() {
        guard let candidate = enterCandidate else { return }
        guard ProcessInfo.processInfo.systemUptime <= candidate.deadline,
              latest.status == "ready", latest.source == candidate.source,
              let composer = observedComposer, CFEqual(composer, candidate.composer),
              let currentDraft = latest.draft else {
            clearEnterCandidate()
            return
        }
        if currentDraft.isEmpty {
            clearEnterCandidate()
            submissions.append((UUID().uuidString, candidate.source, candidate.draft))
            sendSubmission()
        } else if !currentDraft.utf8.elementsEqual(candidate.draft.utf8) {
            clearEnterCandidate()
        }
    }

    private func sendSubmission() {
        guard !sendingSubmission, let submission = submissions.first else { return }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/submission")!)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: [
            "event_id": submission.id, "source": submission.source, "draft": submission.draft,
        ])
        sendingSubmission = true
        session.dataTask(with: request) { [weak self] _, response, _ in
            let status = (response as? HTTPURLResponse)?.statusCode
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.sendingSubmission = false
                if status == 200 {
                    self.submissions.removeFirst()
                    self.sendSubmission()
                } else if let status = status, (400..<500).contains(status) {
                    self.submissions.removeFirst()
                    fputs("Backend rejected a submission (HTTP \(status)). Check --submissions-csv.\n", stderr)
                    self.sendSubmission()
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                        self?.sendSubmission()
                    }
                }
            }
        }.resume()
    }

    private func observeApp(_ app: NSRunningApplication, element: AXUIElement) {
        guard observer == nil else { return }
        var created: AXObserver?
        let result = AXObserverCreate(app.processIdentifier, { _, _, _, context in
            guard let context = context else { return }
            Unmanaged<Collector>.fromOpaque(context).takeUnretainedValue().scheduleRead()
        }, &created)
        guard result == .success, let created = created else { return }
        observer = created
        receivesFocusEvents = addNotification(kAXFocusedUIElementChangedNotification, to: element)
        CFRunLoopAddSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(created), .commonModes)
    }

    private func addNotification(_ name: String, to element: AXUIElement) -> Bool {
        guard let observer = observer else { return false }
        let result = AXObserverAddNotification(
            observer, element, name as CFString, Unmanaged.passUnretained(self).toOpaque()
        )
        return result == .success || result == .notificationAlreadyRegistered
    }

    private func observeComposer(_ composer: AXUIElement?) {
        if let current = observedComposer, let next = composer, CFEqual(current, next) { return }
        if let observer = observer, let current = observedComposer {
            AXObserverRemoveNotification(observer, current, kAXValueChangedNotification as CFString)
        }
        observedComposer = nil
        receivesValueEvents = false
        if let composer = composer, observer != nil {
            observedComposer = composer
            receivesValueEvents = addNotification(kAXValueChangedNotification, to: composer)
        }
    }

    private func stopObserving() {
        observeComposer(nil)
        if let observer = observer {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .commonModes)
        }
        observer = nil
        receivesFocusEvents = false
    }

    private func scheduleRead() {
        guard eventRead == nil else { return }
        eventRead = Timer.scheduledTimer(withTimeInterval: 0.08, repeats: false) { [weak self] _ in
            self?.eventRead = nil
            self?.tick()
        }
    }

    private func updateWatchdog() {
        let bundle = activeApp?.bundleIdentifier
        let supported = bundle.map {
            browsers[$0] != nil || $0 == codexBundleID || $0 == environment["TOK_NATIVE_BUNDLE_ID"]
        } ?? false
        let permission = supported && AXIsProcessTrusted()
        let interval = permission && (!receivesFocusEvents ||
            (observedComposer != nil && !receivesValueEvents)) ? 0.4 : 1.5
        if supported, watchdog?.timeInterval == interval { return }
        watchdog?.invalidate()
        watchdog = nil
        if supported {
            watchdog = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
                self?.tick()
            }
            watchdog?.tolerance = interval / 5
        }
    }

    private func snapshot() -> Snapshot {
        guard let app = activeApp, let bundle = app.bundleIdentifier else {
            return Snapshot(status: "inactive")
        }
        let source: String
        let composerIDs: Set<String>
        let browser = browsers[bundle]
        if let browser = browser {
            source = browser
            composerIDs = ["prompt-textarea", "pending-home-input"]
        } else if bundle == codexBundleID {
            source = "codex"
            composerIDs = Set([environment["TOK_CODEX_COMPOSER_ID"]].compactMap { $0 })
        } else if bundle == environment["TOK_NATIVE_BUNDLE_ID"] {
            source = "chatgpt"
            composerIDs = Set([environment["TOK_NATIVE_COMPOSER_ID"]].compactMap { $0 })
        } else {
            reportProbe("Waiting for Safari, Chrome, Codex, or configured native ChatGPT.")
            return Snapshot(status: "inactive")
        }
        let unavailable = Snapshot(source: source, status: "unavailable")
        guard AXIsProcessTrusted() else {
            stopObserving()
            reportProbe("Accessibility permission is required.")
            return unavailable
        }

        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(appElement, 0.08)
        observeApp(app, element: appElement)
        var verifiedComposer: AXUIElement?
        defer { observeComposer(verifiedComposer) }
        guard let focused = attribute(appElement, kAXFocusedUIElementAttribute),
              CFGetTypeID(focused) == AXUIElementGetTypeID() else {
            reportProbe("\(source): no focused Accessibility element. Click the message box.")
            return unavailable
        }
        var element = focused as! AXUIElement
        var composer: AXUIElement?
        var focusedEditor: AXUIElement?
        var anonymousSafariEditor: AXUIElement?
        var webAreaFound = false
        var pageURL: URL?
        var roles: [String] = []
        let deadline = ProcessInfo.processInfo.systemUptime + (source == "safari" ? 0.6 : 0.2)
        var timedOut = false
        for depth in 0..<(source == "safari" ? 40 : 12) {
            if ProcessInfo.processInfo.systemUptime >= deadline {
                timedOut = true
                break
            }
            let node = AccessibilityNode(element)
            let role = node.role
            let editable = role == kAXTextAreaRole || role == kAXTextFieldRole
            if depth == 0, editable {
                focusedEditor = element
                if source == "safari", role == kAXTextAreaRole, node.identifiers.isEmpty {
                    anonymousSafariEditor = element
                }
            }
            if probe {
                let identifiers = node.identifiers.isEmpty ? "-" : node.identifiers.joined(separator: "/")
                roles.append("\(role ?? "?") id=\(identifiers)")
            }
            if composer == nil, node.identifiers.contains(where: composerIDs.contains) {
                composer = editable ? element : (browser != nil || source == "codex" ? focusedEditor : nil)
                if composer != nil, browser == nil, !probe { break }
            }
            if browser != nil, role == "AXWebArea" {
                webAreaFound = true
                pageURL = urlAttribute(element, kAXURLAttribute)
                if pageURL == nil, source == "safari" {
                    pageURL = urlAttribute(element, kAXDocumentAttribute)
                }
                break
            }
            guard let next = node.parent, !CFEqual(element, next) else { break }
            element = next
        }
        if browser != nil {
            if source == "safari", pageURL == nil,
               let window = elementAttribute(appElement, kAXFocusedWindowAttribute) {
                pageURL = urlAttribute(window, kAXDocumentAttribute)
                if pageURL == nil, webAreaFound {
                    pageURL = safariAddressURL(in: window)
                }
            }
            guard pageURL?.scheme?.lowercased() == "https",
                  pageURL?.host?.lowercased() == "chatgpt.com" else {
                let reason: String
                if pageURL != nil {
                    reason = "page is outside chatgpt.com"
                } else if timedOut {
                    reason = "Accessibility lookup timed out before the page could be verified"
                } else if webAreaFound {
                    reason = "web area found, but no page address was exposed"
                } else {
                    reason = "no web area or page address was exposed"
                }
                reportProbe("\(source): \(reason) — " + roles.joined(separator: " → "))
                return Snapshot(status: "inactive")
            }
        }
        var result = composer == nil ? "composer not identified" : "composer detected"
        if source == "codex", composerIDs.isEmpty {
            result = "app detected; composer ID not configured"
        }
        if composer == nil, let editor = anonymousSafariEditor {
            let labels = [kAXPlaceholderValueAttribute, kAXTitleAttribute, kAXDescriptionAttribute]
            let hasComposerLabel = labels.contains { name in
                guard let label = attribute(editor, name) as? String else { return false }
                return ["ask chatgpt", "message chatgpt"].contains(
                    label.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                )
            }
            if hasComposerLabel {
                composer = editor
                result = "composer detected by label"
            } else if allowUnidentifiedSafariEditor {
                composer = editor
                result = "using focused text area on verified chatgpt.com (test mode)"
            } else {
                result = "focused text area has no verified composer identifier or label"
            }
        }
        reportProbe("\(source): \(result) — " + roles.joined(separator: " → "))
        guard let composer = composer else { return unavailable }
        verifiedComposer = composer
        if probe { return unavailable }
        guard let draft = attribute(composer, kAXValueAttribute) as? String else { return unavailable }
        let visibleDraft = draft.trimmingCharacters(in: emptyDraftCharacters)
        // Codex can return placeholder text followed by an editor line break
        // even when AXPlaceholderValue is unavailable.
        let empty = visibleDraft.isEmpty || (
            source == "codex" &&
            (draft == "Work with Codex\n" || draft == "Do anything\n" ||
             visibleDraft == attribute(composer, kAXPlaceholderValueAttribute) as? String)
        )
        return Snapshot(source: source, status: "ready", draft: empty ? "" : draft)
    }

    private func reportProbe(_ message: String) {
        guard probe, message != lastProbe else { return }
        lastProbe = message
        print(message)
    }

    private func tick() {
        latest = snapshot()
        checkSubmission()
        updateWatchdog()
        publish()
    }

    private func publish() {
        guard !probe, !sending else { return }
        let current = latest
        let refresh = current.source != nil && ProcessInfo.processInfo.systemUptime - lastSentAt >= 3
        guard current != lastSent || refresh else { return }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/draft")!)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var payload: [String: Any] = [
            "revision": DispatchTime.now().uptimeNanoseconds,
            "source": current.source as Any? ?? NSNull(),
            "status": current.status,
        ]
        payload["draft"] = current.draft
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return }
        request.httpBody = body
        sending = true
        session.dataTask(with: request) { [weak self] _, response, _ in
            let delivered = (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.sending = false
                if self.backendConnected != delivered {
                    self.backendConnected = delivered
                    if delivered {
                        fputs("Connected to Tok backend at http://127.0.0.1:\(self.port)/.\n", stderr)
                    } else {
                        fputs("Tok backend did not accept the update. Check http://127.0.0.1:\(self.port)/health.\n", stderr)
                    }
                }
                if delivered {
                    self.lastSent = current
                    self.lastSentAt = ProcessInfo.processInfo.systemUptime
                }
                if self.latest != current {
                    self.publish()
                }
            }
        }.resume()
    }
}

let port = Int(ProcessInfo.processInfo.environment["TOK_PORT"] ?? "8765")
guard let port = port, (1...65535).contains(port) else {
    fputs("TOK_PORT must be between 1 and 65535.\n", stderr)
    exit(1)
}
private let collector = Collector(port: port)
collector.start()
RunLoop.main.run()
