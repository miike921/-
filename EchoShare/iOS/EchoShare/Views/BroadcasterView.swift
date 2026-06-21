import SwiftUI
import ReplayKit

struct BroadcasterView: View {

    @EnvironmentObject var appModel: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 24) {
                    connectionInfoCard
                    broadcastControlCard
                    instructionCard
                    warningCard
                }
                .padding()
            }
            .navigationTitle("配信側 (Broadcaster)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("戻る") { dismiss() }
                }
            }
        }
    }

    // MARK: - 接続情報カード
    private var connectionInfoCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("接続設定", systemImage: "checkmark.circle.fill")
                .font(.headline)
                .foregroundColor(.green)

            HStack {
                Image(systemName: "network")
                    .foregroundColor(.secondary)
                    .frame(width: 20)
                Text(appModel.serverURL)
                    .font(.subheadline)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            HStack {
                Image(systemName: "lock.fill")
                    .foregroundColor(.secondary)
                    .frame(width: 20)
                Text("ルームID: \(appModel.roomId)")
                    .font(.subheadline)
                    .fontWeight(.semibold)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(14)
    }

    // MARK: - 配信開始ボタンカード
    private var broadcastControlCard: some View {
        VStack(spacing: 18) {
            Text("画面配信を開始")
                .font(.title2.bold())

            Text("以下のボタンをタップして\n「EchoShareBroadcast」を選択し\n「配信を開始」をタップしてください")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .font(.subheadline)

            // ⚠️ preferredExtension はご自身のBundle IDに変更してください
            // 例: "com.yourname.EchoShare.EchoShareBroadcast"
            BroadcastPickerRepresentable(
                preferredExtension: "com.echoshare.EchoShare.EchoShareBroadcast"
            )
            .frame(width: 80, height: 80)

            Text("配信中は画面上部に赤いインジケーターが表示されます")
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(14)
    }

    // MARK: - 手順カード
    private var instructionCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("操作手順", systemImage: "list.number")
                .font(.headline)

            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                HStack(alignment: .top, spacing: 12) {
                    Text("\(index + 1)")
                        .font(.callout.bold())
                        .foregroundColor(.white)
                        .frame(width: 24, height: 24)
                        .background(Color.blue)
                        .clipShape(Circle())

                    Text(step)
                        .font(.subheadline)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(14)
    }

    private let steps = [
        "上の「配信開始」ボタンをタップ",
        "表示されたメニューで「EchoShareBroadcast」をタップ",
        "「配信を開始」をタップ",
        "ホームボタン（またはスワイプ）でGEエコーアプリに切り替える",
        "エコーで画像を描出する → 遠隔地の視聴側iPadに自動的に配信されます",
        "配信を止めるには：画面上部の赤いバーをタップ → 「配信を停止」"
    ]

    // MARK: - 注意カード
    private var warningCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("注意事項", systemImage: "exclamationmark.triangle.fill")
                .font(.headline)
                .foregroundColor(.orange)

            Text("• GEアプリが画面キャプチャを禁止している場合、黒い画面が配信されることがあります")
            Text("• 事前にZoomやFaceTimeの画面共有でGEアプリが映るかご確認ください")
            Text("• 患者さんの同意と施設の規定に従ってご使用ください")
        }
        .font(.caption)
        .foregroundColor(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color.orange.opacity(0.1))
        .cornerRadius(14)
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.orange.opacity(0.3), lineWidth: 1))
    }
}

// MARK: - RPSystemBroadcastPickerView ラッパー
struct BroadcastPickerRepresentable: UIViewRepresentable {
    var preferredExtension: String

    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let picker = RPSystemBroadcastPickerView(frame: CGRect(x: 0, y: 0, width: 80, height: 80))
        picker.preferredExtension = preferredExtension
        picker.showsMicrophoneButton = false
        return picker
    }

    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {}
}
