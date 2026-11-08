import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

@main
struct PhoneUseWidgets: WidgetBundle {
    var body: some Widget {
        AgentLiveActivity()
    }
}

struct AgentLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: AgentActivityAttributes.self) { context in
            LockScreenView(state: context.state, pcName: context.attributes.pcName)
                .padding()
                .activityBackgroundTint(Color.black.opacity(0.6))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            let s = context.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Label(s.paused ? "Paused" : "Agent", systemImage: icon(s))
                        .font(.caption)
                        .foregroundStyle(s.paused ? .orange : .cyan)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text("\(s.steps) steps").font(.caption).monospacedDigit()
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(s.action).font(.headline).lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack {
                        Text(timerInterval: s.startDate...Date.distantFuture, countsDown: false)
                            .monospacedDigit().foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
                        Spacer()
                        ControlButton(paused: s.paused)
                    }
                }
            } compactLeading: {
                Image(systemName: icon(s)).foregroundStyle(s.paused ? .orange : .cyan)
            } compactTrailing: {
                Text("\(s.steps)").monospacedDigit()
            } minimal: {
                Image(systemName: icon(s)).foregroundStyle(s.paused ? .orange : .cyan)
            }
        }
    }
}

private func icon(_ s: AgentActivityAttributes.ContentState) -> String {
    s.paused ? "pause.circle.fill" : "cursorarrow.rays"
}

struct LockScreenView: View {
    var state: AgentActivityAttributes.ContentState
    var pcName: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon(state))
                .font(.title)
                .foregroundStyle(state.paused ? .orange : .cyan)
            VStack(alignment: .leading, spacing: 2) {
                Text(state.paused ? "Paused" : state.action).font(.headline).lineLimit(1)
                HStack(spacing: 4) {
                    Text("\(state.steps) steps ·").fixedSize()
                    Text(timerInterval: state.startDate...Date.distantFuture, countsDown: false)
                        .frame(width: 72, alignment: .leading)
                }
                .font(.subheadline).monospacedDigit().foregroundStyle(.secondary).lineLimit(1)
                Text(pcName).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            ControlButton(paused: state.paused)
        }
    }
}

struct ControlButton: View {
    var paused: Bool

    var body: some View {
        if paused {
            Button(intent: ResumeIntent()) { Label("Resume", systemImage: "play.fill").lineLimit(1).fixedSize() }
                .tint(.green)
        } else {
            Button(intent: TakeOverIntent()) { Label("Take over", systemImage: "hand.raised.fill").lineLimit(1).fixedSize() }
                .tint(.orange)
        }
    }
}
