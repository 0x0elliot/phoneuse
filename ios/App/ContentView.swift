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
        .navigationTitle("PhoneUse")
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
                        row("Mirror Audio", "speaker.wave.2", busy: "audio")
                    }
                    .accessibilityIdentifier("audio")
                    if s.audio.needsRemirror == true {
                        Label("Start Screen Mirroring to PhoneUse again.", systemImage: "airplayvideo")
                            .foregroundStyle(.orange)
                    }
                } header: { Text("Mirror") }
                }
                .disabled(offline)
            }
            pcSection
        }
        .navigationTitle("PhoneUse")
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
            LabeledContent {
                if let steps = s.agent.steps, s.agent.state != "idle" { Text("\(steps) steps").monospacedDigit() }
            } label: {
                if s.agent.state == "driving" {
                    Label { Text(agentText(s.agent)) } icon: { ProgressView().tint(.blue) }
                } else {
                    Label(agentText(s.agent), systemImage: s.agent.state == "paused" ? "pause.circle" : "iphone")
                }
            }
            .accessibilityIdentifier("agentState")
            .listRowBackground(s.agent.state == "driving" ? AnyView(GlowBackground()) : AnyView(Color(.secondarySystemGroupedBackground)))
            if let pending = s.session?.pending {
                Label("An agent wants to start\(pending.action.map { ": \($0)" } ?? "")", systemImage: "person.badge.clock")
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
                    row("Take Over", "hand.raised", busy: "agent")
                }
                .accessibilityIdentifier("takeover")
            } else if s.agent.state == "paused" {
                Button { Task { await model.resume() } } label: { row("Resume", "play", busy: "agent") }
                    .accessibilityIdentifier("resume")
            }
            if let session = s.session {
                Toggle(isOn: binding(session.ask) { on in await model.setSessionAsk(on) }) {
                    Label("Ask before agent starts", systemImage: "hand.raised.square")
                }
                .accessibilityIdentifier("sessionAsk")
            }
        }
    }

    private func agentText(_ a: PCState.Agent) -> String {
        switch a.state {
        case "driving": return (a.action?.isEmpty == false ? a.action! : "Working")
        case "paused": return "Paused"
        default: return "Idle"
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
            Button { model.startTestActivity() } label: { Label("Test Live Activity", systemImage: "platter.filled.top.iphone") }
                .accessibilityIdentifier("testActivity")
            Button { Task { await model.endActivities() } } label: { Label("End Live Activities", systemImage: "xmark.circle") }
                .accessibilityIdentifier("endActivity")
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

/// A slowly turning blue-purple border with a soft glow, like the browser mirror's, for the Agent row while an
/// agent drives the phone.
struct GlowBackground: View {
    var body: some View {
        TimelineView(.animation) { context in
            let angle = Angle.degrees(context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 4) * 90)
            let gradient = AngularGradient(colors: [.blue, .purple, .pink, .cyan, .blue], center: .center, angle: angle)
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(.secondarySystemGroupedBackground))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(gradient, lineWidth: 2))
                .shadow(color: .purple.opacity(0.5), radius: 8)
        }
    }
}
