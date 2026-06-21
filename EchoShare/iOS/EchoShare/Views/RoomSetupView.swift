import SwiftUI

struct RoomSetupView: View {

    @EnvironmentObject var appModel: AppModel
    @State private var showBroadcaster = false
    @State private var showViewer      = false

    private var canConnect: Bool {
        !appModel.roomId.trimmingCharacters(in: .whitespaces).isEmpty &&
        !appModel.serverURL.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 28) {
                headerSection
                serverSection
                roomSection
                roleSection
            }
            .padding()
        }
        .navigationTitle("EchoShare")
        .navigationBarTitleDisplayMode(.large)
        .fullScreenCover(isPresented: $showBroadcaster) {
            BroadcasterView().environmentObject(appModel)
        }
        .fullScreenCover(isPresented: $showViewer) {
            ViewerView().environmentObject(appModel)
        }
    }

    // MARK: - Header
    private var headerSection: some View {
        VStack(spacing: 8) {
            Image(systemName: "waveform.circle.fill")
                .font(.system(size: 64))
                .foregroundColor(.blue)
                .padding(.top, 20)
            Text("エコー画像 遠隔共有")
                .font(.title2.bold())
            Text("GEエコーの画像をリアルタイムで遠隔地に配信します")
                .font(.subheadline)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
    }

    // MARK: - Server URL
    private var serverSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("中継サーバーURL", systemImage: "network")
                .font(.headline)

            TextField("ws://your-server:8080", text: $appModel.serverURL)
                .textFieldStyle(.roundedBorder)
                .keyboardType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)

            Text("管理者から提供されたサーバーURLを入力")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(14)
    }

    // MARK: - Room ID
    private var roomSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("ルームID（接続コード）", systemImage: "lock.fill")
                .font(.headline)

            TextField("例: ward3-echo-01", text: $appModel.roomId)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)

            Text("配信側・視聴側で同じIDを入力してください")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(14)
    }

    // MARK: - Role buttons
    private var roleSection: some View {
        VStack(spacing: 12) {
            Text("このiPadの役割を選択")
                .font(.headline)

            HStack(spacing: 16) {
                // Broadcaster
                Button {
                    showBroadcaster = true
                } label: {
                    roleCard(
                        icon: "rectangle.on.rectangle.angled",
                        title: "配信側",
                        description: "エコーを使用している iPad",
                        color: .blue
                    )
                }
                .disabled(!canConnect)

                // Viewer
                Button {
                    showViewer = true
                } label: {
                    roleCard(
                        icon: "tv.fill",
                        title: "視聴側",
                        description: "遠隔地で確認する iPad",
                        color: .green
                    )
                }
                .disabled(!canConnect)
            }

            if !canConnect {
                Text("サーバーURLとルームIDを入力してください")
                    .font(.caption)
                    .foregroundColor(.orange)
            }
        }
    }

    private func roleCard(icon: String, title: String, description: String, color: Color) -> some View {
        VStack(spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 44))
                .foregroundColor(color)

            Text(title)
                .font(.headline)
                .foregroundColor(.primary)

            Text(description)
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 20)
        .background(color.opacity(0.08))
        .cornerRadius(16)
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(color.opacity(canConnect ? 1 : 0.3), lineWidth: 1.5)
        )
        .opacity(canConnect ? 1 : 0.5)
    }
}
