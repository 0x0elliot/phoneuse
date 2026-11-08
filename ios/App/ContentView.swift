import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        NavigationStack {
            if model.pairing == nil {
                UnpairedView()
            } else {
                SettingsView()
            }
        }
        .sheet(item: Binding(get: { model.foregroundRequest }, set: { _ in })) { request in
            RequestSheet(request: request)
                .interactiveDismissDisabled()
                .presentationDetents([.medium])
        }
        .alert("Mirror again", isPresented: $model.askRemirror) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Open Control Center, tap Screen Mirroring, and choose PhoneUse.")
        }
    }
}

struct UnpairedView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ContentUnavailableView {
            Label("Not Paired", systemImage: "link")
        } description: {
            Text("Run `phoneuse app pair` on the PC.")
        } actions: {
            Button("Paste Pairing Link") {
                if let text = UIPasteboard.general.string, let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)) {
                    model.pair(from: url)
                } else {
                    model.error = "The clipboard has no pairing link."
                }
            }
            .buttonStyle(.borderedProminent)
            if let error = model.error { Text(error).foregroundStyle(.red).font(.footnote) }
        }
        .navigationTitle("Phone Use")
    }
}

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var passcodeSheet = false
    @State private var confirmForget = false
    @State private var confirmUnpair = false

    private var s: PCState? { model.state }
    private var offline: Bool { !model.reachable || s == nil }

    var body: some View {
        Form {
            statusSection
            if model.notificationsOff {
                Section {
                    Button { Task { await model.turnOnNotifications() } } label: {
                        Label("Turn On Notifications", systemImage: "bell.badge")
                    }
                    .accessibilityIdentifier("turnOnNotifications")
                } footer: {
                    Text("So you can approve agents and unlocks while the phone mirrors.")
                }
            }
            if let s {
                Group {
                agentSection(s)
                unlockSection(s)
                Section("Phone") {
                    Toggle(isOn: binding(s.awake) { on in await model.setAwake(on) }) {
                        Label("Keep Awake", systemImage: "sun.max")
                    }
                    .accessibilityIdentifier("awake")
                    Button {
                        Task { await model.toggleKeyboard() }
                    } label: {
                        row("Show or Hide Keyboard", "keyboard", busy: "keyboard")
                    }
                    .accessibilityIdentifier("keyboard")
                    pointerRow
                }
                bridgeSection(s)
                Section {
                    Toggle(isOn: binding(s.audio.on) { on in await model.setAudio(on) }) {
                        row("Sound on the PC", "speaker.wave.2", busy: "audio")
                    }
                    .accessibilityIdentifier("audio")
                    if s.audio.needsRemirror == true {
                        Label("Start Screen Mirroring to PhoneUse again.", systemImage: "airplayvideo")
                            .foregroundStyle(.orange)
                    }
                } header: { Text("Mirror") } footer: {
                    Text("Off mutes it; iOS can't keep sound on the phone while mirroring.")
                }
                }
                .disabled(offline)
            }
            pcSection
        }
        .navigationTitle("Phone Use")
        .refreshable { await model.refresh() }
        .sheet(isPresented: $passcodeSheet) { PasscodeSheet() }
    }

    // MARK: Sections

    private var statusSection: some View {
        Section {
            if offline {
                Label("Can't reach \(model.pairing?.name ?? "the PC").", systemImage: "wifi.exclamationmark")
                    .foregroundStyle(.orange)
                    .accessibilityIdentifier("offline")
            }
            if let s {
                LabeledContent {
                    Text(s.mirroring ? "Mirroring" : "Not mirroring")
                } label: {
                    Label(s.pc.name, systemImage: "desktopcomputer")
                }
                LabeledContent {
                    Text(s.bluetooth.connected ? (s.bluetooth.via == "bridge" ? "Via bridge" : "Via PC") : "Off")
                } label: {
                    Label("Bluetooth", systemImage: "dot.radiowaves.left.and.right")
                }
            }
            if let error = model.error {
                Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.red).font(.footnote)
                    .accessibilityIdentifier("error")
            }
        }
    }

    private func agentSection(_ s: PCState) -> some View {
        Section("Agent") {
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text(agentTitle(s.agent)).font(.headline)
                    if let detail = agentDetail(s), !detail.isEmpty {
                        Text(detail).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
            } icon: {
                if s.agent.state == "driving" {
                    let color: Color = s.agent.phase == "thinking" ? .purple : .blue
                    ZStack {
                        SpinningRing(color: color)
                        RobotView(pose: .pose(phase: s.agent.phase, frame: 0), size: 13, color: color)
                    }
                    .frame(width: 24, height: 24)
                } else {
                    Image(systemName: s.agent.state == "paused" ? "pause.circle.fill" : "person.fill")
                        .font(.system(size: 17, weight: .semibold))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(s.agent.state == "paused" ? Color.orange : Color.gray)
                }
            }
            .accessibilityIdentifier("agentState")
            .listRowBackground(s.agent.state == "driving" ? AnyView(GlowBackground()) : AnyView(Color(.secondarySystemGroupedBackground)))
            if let pending = s.session?.pending {
                Label(pending.deadline == nil ? "Agent requests control" : "Agent taking control soon",
                      systemImage: "hand.raised.fill")
                    .foregroundStyle(.orange)
                    .accessibilityIdentifier("sessionRequest")
                HStack {
                    Button("Allow") { Task { await model.answerSession(id: pending.id, approve: true) } }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("allowSession")
                    Button("Deny", role: .destructive) {
                        Task { await model.answerSession(id: pending.id, approve: false) }
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("denySession")
                    if model.busy.contains("session") { Spacer(); ProgressView() }
                }
            }
            if s.agent.state == "driving" {
                Button(role: .destructive) { Task { await model.takeOver() } } label: {
                    row("Take Over", "hand.raised.fill", busy: "agent")
                }
                .accessibilityIdentifier("takeover")
            } else if s.agent.state == "paused" {
                Button { Task { await model.resume() } } label: { row("Resume", "play.fill", busy: "agent") }
                    .accessibilityIdentifier("resume")
            }
            if let session = s.session {
                StartModeRow(session: session)
            }
        }
    }

    /// Who has control, worded as in the Live Activity.
    private func agentTitle(_ a: PCState.Agent) -> String {
        switch a.state {
        case "driving":
            switch a.phase {
            case "acting": return "Agent is tapping"
            case "reading": return "Agent is reading"
            case "thinking": return "Agent is thinking"
            default: return "Agent is working"
            }
        case "paused": return "You took over"
        default: return "You're in control"
        }
    }

    /// What's happening.
    private func agentDetail(_ s: PCState) -> String? {
        switch s.agent.state {
        case "driving":
            let steps = s.agent.steps ?? 0
            let count = steps <= 0 ? nil : steps == 1 ? "1 step" : "\(steps) steps"
            return [s.agent.action, count].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
        case "paused": return "The agent is paused"
        default: return s.mirroring ? "Phone Use is mirroring your screen" : nil
        }
    }

    private func unlockSection(_ s: PCState) -> some View {
        Section("Unlock") {
            if let pending = s.unlock.pending {
                Label("Unlock requested", systemImage: "lock.open").foregroundStyle(.orange)
                HStack {
                    Button("Unlock") { Task { await model.answerUnlock(id: pending.id, approve: true) } }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("approveUnlock")
                    Button("Deny", role: .destructive) {
                        Task { await model.answerUnlock(id: pending.id, approve: false) }
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("denyUnlock")
                    if model.busy.contains("unlock") { Spacer(); ProgressView() }
                }
            }
            LabeledContent {
                Text(s.unlock.passcodeSaved ? "Saved" : "Not saved")
            } label: {
                Label("Passcode", systemImage: "key")
            }
            .accessibilityIdentifier("passcodeStatus")
            Button { passcodeSheet = true } label: {
                row(s.unlock.passcodeSaved ? "Replace Passcode" : "Save Passcode", "square.and.pencil", busy: "passcode")
            }
            .accessibilityIdentifier("savePasscode")
            if s.unlock.passcodeSaved {
                Button(role: .destructive) { confirmForget = true } label: { Label("Forget Passcode", systemImage: "trash") }
                    .accessibilityIdentifier("forgetPasscode")
                    .confirmationDialog("Forget the passcode?", isPresented: $confirmForget, titleVisibility: .visible) {
                        Button("Forget", role: .destructive) { Task { await model.forgetPasscode() } }
                    }
            }
        }
    }

    private var pointerRow: some View {
        HStack {
            Label("Pointer", systemImage: "cursorarrow")
            Spacer()
            if model.busy.contains("pointer") {
                ProgressView()
            } else {
                Picker("Pointer", selection: Binding(
                    get: { model.pointerOn },
                    set: { on in if let on { Task { await model.setPointer(on) } } }
                )) {
                    Text("On").tag(Bool?.some(true))
                    Text("Off").tag(Bool?.some(false))
                }
                .pickerStyle(.segmented)
                .fixedSize()
                .accessibilityIdentifier("pointer")
            }
        }
    }

    @ViewBuilder
    private func bridgeSection(_ s: PCState) -> some View {
        Section("Bridge") {
            if let b = s.bridge {
                LabeledContent {
                    Text(b.online ? (b.rttMs.map { "Online, \(Int($0)) ms" } ?? "Online") : "Offline")
                        .foregroundStyle(b.online ? Color.secondary : Color.orange)
                } label: {
                    Label(b.ssid ?? "Bridge", systemImage: "cpu")
                }
                .accessibilityIdentifier("bridgeStatus")
                Toggle(isOn: binding(b.use) { on in await model.setBridge(on) }) {
                    row("Input Through Bridge", "arrow.triangle.branch", busy: "bridge")
                }
                .accessibilityIdentifier("bridgeUse")
                NavigationLink {
                    NetworksView(current: b.ssid)
                } label: {
                    Label("Wi-Fi Network", systemImage: "wifi")
                }
                .accessibilityIdentifier("bridgeNetwork")
            } else {
                Label("No bridge", systemImage: "cpu").foregroundStyle(.secondary)
            }
        }
    }

    private var pcSection: some View {
        Section {
            if let p = model.pairing {
                LabeledContent("Paired with", value: p.name)
                LabeledContent("Address", value: "\(p.host):\(p.port)")
            }
            Button("Unpair", role: .destructive) { confirmUnpair = true }
                .confirmationDialog("Unpair from this PC?", isPresented: $confirmUnpair, titleVisibility: .visible) {
                    Button("Unpair", role: .destructive) { model.unpair() }
                }
        } header: { Text("PC") }
    }

    // MARK: Helpers

    /// A toggle binding that shows the PC's value and sends a change at once.
    private func binding(_ value: Bool, _ apply: @escaping (Bool) async -> Void) -> Binding<Bool> {
        Binding(get: { value }, set: { on in Task { await apply(on) } })
    }

    private func row(_ title: String, _ icon: String, busy key: String) -> some View {
        HStack {
            Label(title, systemImage: icon)
            if model.busy.contains(key) { Spacer(); ProgressView() }
        }
    }
}

struct PasscodeSheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""

    var body: some View {
        NavigationStack {
            Form {
                SecureField("Passcode", text: $code)
                    .keyboardType(.numberPad)
                    .textContentType(.oneTimeCode)
                    .accessibilityIdentifier("passcodeField")
            }
            .navigationTitle("iPhone Passcode")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        let c = code
                        dismiss()
                        Task { await model.savePasscode(c) }
                    }
                    .disabled(code.count < 4)
                    .accessibilityIdentifier("passcodeSave")
                }
            }
        }
        .presentationDetents([.medium])
    }
}

struct NetworksView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    var current: String?
    @State private var networks: [BridgeNetwork]?
    @State private var loadError: String?
    @State private var chosen: BridgeNetwork?
    @State private var password = ""
    @State private var moving = false

    var body: some View {
        List {
            if let loadError { Label(loadError, systemImage: "exclamationmark.triangle").foregroundStyle(.red) }
            if let networks {
                ForEach(networks) { n in
                    Button {
                        password = ""
                        if n.secure { chosen = n } else { Task { await move(n, nil) } }
                    } label: {
                        HStack {
                            Text(n.ssid).foregroundStyle(Color.primary)
                            Spacer()
                            if n.ssid == current { Image(systemName: "checkmark") }
                            if n.secure { Image(systemName: "lock.fill").foregroundStyle(.secondary) }
                            Image(systemName: "wifi", variableValue: strength(n.rssi)).foregroundStyle(.secondary)
                        }
                    }
                    .accessibilityIdentifier("network-\(n.ssid)")
                }
            } else if loadError == nil {
                HStack { Spacer(); ProgressView(); Spacer() }
            }
        }
        .navigationTitle("Bridge Wi-Fi")
        .disabled(moving)
        .overlay { if moving { ProgressView("Moving the bridge…").padding().background(.regularMaterial, in: .rect(cornerRadius: 12)) } }
        .task { await load() }
        .refreshable { await load() }
        .alert(chosen?.ssid ?? "", isPresented: Binding(get: { chosen != nil }, set: { if !$0 { chosen = nil } })) {
            SecureField("Password", text: $password).accessibilityIdentifier("wifiPassword")
            Button("Cancel", role: .cancel) { chosen = nil }
            Button("Join") {
                if let n = chosen { Task { await move(n, password) } }
                chosen = nil
            }
        } message: {
            Text("The bridge's password for this network")
        }
    }

    private func strength(_ rssi: Int) -> Double { min(1, max(0.1, Double(rssi + 90) / 50)) }

    private func load() async {
        do {
            networks = try await model.networks()
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func move(_ n: BridgeNetwork, _ password: String?) async {
        moving = true
        let ok = await model.moveBridge(ssid: n.ssid, password: password)
        moving = false
        if ok { dismiss() } else { loadError = model.error }
    }
}

/// A soft blue-purple-pink glow that slowly turns around the Agent row's edges while an agent drives, like Apple
/// Intelligence's edge glow: a blurred gradient band with no hard stroke.
struct GlowBackground: View {
    var body: some View {
        TimelineView(.animation) { context in
            let angle = Angle.degrees(context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 6) * 60)
            let gradient = AngularGradient(colors: [.blue, .purple, .pink, .purple, .blue], center: .center, angle: angle)
            ZStack {
                Color(.secondarySystemGroupedBackground)
                RoundedRectangle(cornerRadius: 12)
                    .strokeBorder(gradient, lineWidth: 14)
                    .blur(radius: 14)
                    .opacity(0.55)
            }
        }
    }
}

/// A ring that turns for as long as it's on screen, for the Agent row while an agent drives.
struct SpinningRing: View {
    var color: Color
    @State private var turning = false

    var body: some View {
        Circle()
            .trim(from: 0.1, to: 0.8)
            .stroke(color, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
            .frame(width: 24, height: 24)
            .rotationEffect(.degrees(turning ? 360 : 0))
            .animation(.linear(duration: 1).repeatForever(autoreverses: false), value: turning)
            .onAppear { turning = true }
    }
}

/// A session request while Phone Use is open. iOS doesn't expand the app's own Live Activity while the app is in
/// front, so the app asks here instead; the sheet closes when the request ends, however it was answered.
struct RequestSheet: View {
    @EnvironmentObject var model: AppModel
    var request: PCState.Pending

    private var deadline: Date? {
        request.deadline.map { Date(timeIntervalSince1970: $0) }.flatMap { $0 > Date() ? $0 : nil }
    }

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "hand.raised.fill").font(.system(size: 44, weight: .semibold))
                .symbolRenderingMode(.hierarchical).foregroundStyle(.orange)
            VStack(spacing: 6) {
                if let deadline {
                    HStack(spacing: 6) {
                        Text("Agent taking control in")
                        Text(timerInterval: Date()...deadline, countsDown: true).monospacedDigit()
                    }
                    .font(.title2.bold())
                    if let action = request.action, !action.isEmpty {
                        Text(action).font(.headline).foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                } else {
                    Text("Agent requests control").font(.title2.bold()).multilineTextAlignment(.center)
                    if let action = request.action, !action.isEmpty {
                        Text(action).font(.headline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                }
                if let name = model.pairing?.name { Text(name).font(.subheadline).foregroundStyle(.secondary) }
            }
            HStack(spacing: 14) {
                Button(role: .destructive) { Task { await model.answerSession(id: request.id, approve: false) } } label: {
                    Text(deadline == nil ? "Deny" : "Cancel").font(.title3.bold()).frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.bordered)
                .tint(.red)
                .accessibilityIdentifier("sheetDeny")
                Button { Task { await model.answerSession(id: request.id, approve: true) } } label: {
                    Text(deadline == nil ? "Allow" : "Allow now").font(.title3.bold())
                        .frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
                .accessibilityIdentifier("sheetAllow")
            }
            .disabled(model.busy.contains("session"))
        }
        .padding(24)
    }
}

/// "Agent control" (Always / After a delay / Ask every time) and, for a delay, how long: two ordinary rows.
struct StartModeRow: View {
    @EnvironmentObject var model: AppModel
    var session: PCState.Session

    var body: some View {
        Picker("Agent control", selection: Binding(
            get: { session.currentMode },
            set: { mode in Task { await model.setSessionMode(mode) } }
        )) {
            Text("Always").tag("auto")
            Text("After a delay").tag("countdown")
            Text("Ask every time").tag("ask")
        }
        .pickerStyle(.menu)
        .accessibilityIdentifier("sessionMode")
        if session.currentMode == "countdown" {
            let current = session.seconds ?? 10
            Picker("Delay", selection: Binding(
                get: { current },
                set: { seconds in Task { await model.setSessionSeconds(seconds) } }
            )) {
                ForEach(Array(Set([5, 10, 15, 30, current])).sorted(), id: \.self) { Text("\($0) s").tag($0) }
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("sessionSeconds")
        }
    }
}
