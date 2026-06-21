import Foundation
import Combine

/// 視聴側 iPad のWebSocket 受信サービス
class ViewerStreamingService: NSObject, ObservableObject {

    // MARK: - Published properties
    @Published var isConnected  = false
    @Published var currentFrame: Data?      // 最新の JPEG フレーム
    @Published var statusMessage = "待機中"
    @Published var fps: Double   = 0

    // MARK: - Private
    private var webSocket: URLSessionWebSocketTask?
    private lazy var session = URLSession(configuration: .default)

    private var frameCount  = 0
    private var lastFPSTime = Date()

    // MARK: - Connect
    func connect(serverURL: String, roomId: String) {
        guard let url = URL(string: serverURL) else {
            statusMessage = "無効なURL"
            return
        }

        webSocket = session.webSocketTask(with: url)
        webSocket?.resume()

        let joinMsg = """
        {"type":"join","roomId":"\(roomId)","role":"viewer"}
        """
        webSocket?.send(.string(joinMsg)) { _ in }

        listenLoop()

        DispatchQueue.main.async { self.statusMessage = "サーバーに接続中..." }
    }

    // MARK: - Disconnect
    func disconnect() {
        webSocket?.cancel(with: .goingAway, reason: nil)
        DispatchQueue.main.async {
            self.isConnected  = false
            self.currentFrame = nil
            self.statusMessage = "切断しました"
        }
    }

    // MARK: - Receive loop
    private func listenLoop() {
        webSocket?.receive { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    self.handleControl(text)
                case .data(let data):
                    DispatchQueue.main.async {
                        self.currentFrame = data
                        self.updateFPS()
                        if !self.isConnected {
                            self.isConnected  = true
                            self.statusMessage = "配信受信中"
                        }
                    }
                @unknown default:
                    break
                }
                self.listenLoop()

            case .failure(let error):
                DispatchQueue.main.async {
                    self.isConnected  = false
                    self.statusMessage = "エラー: \(error.localizedDescription)"
                }
            }
        }
    }

    // MARK: - JSON コントロールメッセージ
    private func handleControl(_ text: String) {
        guard
            let data = text.data(using: .utf8),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let type = json["type"] as? String
        else { return }

        DispatchQueue.main.async {
            switch type {
            case "joined":
                self.isConnected = true
                let has = json["hasBroadcaster"] as? Bool ?? false
                self.statusMessage = has ? "配信受信中" : "配信待機中（配信側の接続を待っています）"

            case "broadcaster-joined":
                self.statusMessage = "配信受信中"

            case "stream-ended":
                self.currentFrame  = nil
                self.statusMessage = "配信が終了しました"

            default:
                break
            }
        }
    }

    // MARK: - FPS 計算
    private func updateFPS() {
        frameCount += 1
        let elapsed = Date().timeIntervalSince(lastFPSTime)
        if elapsed >= 1.0 {
            fps = Double(frameCount) / elapsed
            frameCount  = 0
            lastFPSTime = Date()
        }
    }
}
