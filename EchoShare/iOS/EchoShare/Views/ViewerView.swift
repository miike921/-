import SwiftUI

struct ViewerView: View {

    @EnvironmentObject var appModel: AppModel
    @StateObject private var service = ViewerStreamingService()
    @Environment(\.dismiss) private var dismiss

    @State private var scale:  CGFloat  = 1.0
    @State private var offset: CGSize   = .zero
    @State private var showInfo         = false

    var body: some View {
        NavigationView {
            ZStack {
                Color.black.ignoresSafeArea()

                if let data = service.currentFrame,
                   let uiImage = UIImage(data: data) {
                    Image(uiImage: uiImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .scaleEffect(scale)
                        .offset(offset)
                        .gesture(magnifyGesture)
                        .simultaneousGesture(dragGesture)
                        .onTapGesture(count: 2) {
                            withAnimation(.spring()) {
                                scale  = 1.0
                                offset = .zero
                            }
                        }
                } else {
                    waitingView
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarContent }
            .onAppear {
                service.connect(serverURL: appModel.serverURL, roomId: appModel.roomId)
            }
            .onDisappear {
                service.disconnect()
            }
        }
        .preferredColorScheme(.dark)
        .sheet(isPresented: $showInfo) { infoSheet }
    }

    // MARK: - 待機画面
    private var waitingView: some View {
        VStack(spacing: 20) {
            ProgressView()
                .progressViewStyle(.circular)
                .tint(.white)
                .scaleEffect(1.5)

            Text(service.statusMessage)
                .foregroundColor(.white)
                .font(.subheadline)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
    }

    // MARK: - Toolbar
    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .navigationBarLeading) {
            Button {
                service.disconnect()
                dismiss()
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .foregroundColor(.white)
            }
        }

        ToolbarItem(placement: .principal) {
            HStack(spacing: 6) {
                Circle()
                    .fill(service.isConnected ? Color.green : Color.orange)
                    .frame(width: 8, height: 8)
                Text(service.isConnected ? "受信中" : "待機中")
                    .foregroundColor(.white)
                    .font(.subheadline)
            }
        }

        ToolbarItem(placement: .navigationBarTrailing) {
            HStack(spacing: 12) {
                if service.isConnected && service.fps > 0 {
                    Text(String(format: "%.0f fps", service.fps))
                        .foregroundColor(.white.opacity(0.7))
                        .font(.caption.monospacedDigit())
                }
                Button {
                    showInfo = true
                } label: {
                    Image(systemName: "info.circle")
                        .foregroundColor(.white)
                }
            }
        }
    }

    // MARK: - ジェスチャー
    private var magnifyGesture: some Gesture {
        MagnificationGesture()
            .onChanged { v in scale = max(1.0, min(v, 5.0)) }
            .onEnded   { _ in
                if scale < 1.0 { withAnimation { scale = 1.0 } }
            }
    }

    private var dragGesture: some Gesture {
        DragGesture()
            .onChanged { v in
                if scale > 1.0 { offset = v.translation }
            }
            .onEnded { _ in
                if scale <= 1.01 { withAnimation { offset = .zero } }
            }
    }

    // MARK: - 情報シート
    private var infoSheet: some View {
        NavigationView {
            List {
                Section("接続情報") {
                    LabeledContent("サーバー", value: appModel.serverURL)
                    LabeledContent("ルームID", value: appModel.roomId)
                }
                Section("受信状態") {
                    LabeledContent("接続", value: service.isConnected ? "接続中" : "切断中")
                    LabeledContent("フレームレート", value: String(format: "%.1f fps", service.fps))
                    LabeledContent("ステータス", value: service.statusMessage)
                }
                Section("操作") {
                    Text("ダブルタップ: ズームリセット")
                    Text("ピンチ: 拡大/縮小")
                    Text("ドラッグ: 拡大時にパン移動")
                }
            }
            .navigationTitle("情報")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("閉じる") { showInfo = false }
                }
            }
        }
    }
}
