/**
 * EchoShareBroadcast - Broadcast Upload Extension
 *
 * 動作フロー:
 * 1. ユーザーが「配信開始」を選択するとシステムがこのExtensionを起動
 * 2. ReplayKit が画面全体のフレームを processSampleBuffer() に送り続ける
 * 3. フレームを JPEG に変換し、中継サーバーへ WebSocket で直接送信
 * 4. 同じルームに参加している視聴側 iPad が受信・表示する
 *
 * ⚠️ Extensionはメインアプリとは別プロセスで動作します
 *    App Group経由でサーバーURL・ルームIDを共有しています
 */
import ReplayKit
import Foundation
import CoreImage
import UIKit

// MARK: - App Group ID (AppModel.swift と同じ値にする)
private let kAppGroupID = "group.com.echoshare.EchoShare"

// MARK: - 設定定数
private enum Config {
    static let jpegQuality:   CGFloat = 0.65   // JPEG 品質 (0.0-1.0)
    static let maxWidth:      CGFloat = 1280    // 最大幅 (px)
    static let maxHeight:     CGFloat = 720     // 最大高さ (px)
    static let frameSkip:     Int     = 2       // N-1フレームをスキップ (2=約30fps)
}

class SampleHandler: RPBroadcastSampleHandler {

    // MARK: - Private properties
    private var webSocket:  URLSessionWebSocketTask?
    private let session   = URLSession(configuration: .default)
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])
    private var frameCounter = 0
    private var isConnected  = false

    // MARK: - Broadcast lifecycle

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        guard let serverURL = readSetting(key: "serverURL"),
              let roomId    = readSetting(key: "roomId"),
              !serverURL.isEmpty, !roomId.isEmpty,
              let url = URL(string: serverURL)
        else {
            finishBroadcastWithError(makeError("サーバーURLまたはルームIDが設定されていません。\nアプリを開いて設定してください。"))
            return
        }

        webSocket = session.webSocketTask(with: url)
        webSocket?.resume()

        let joinMsg = #"{"type":"join","roomId":"\#(roomId)","role":"broadcaster"}"#
        webSocket?.send(.string(joinMsg)) { [weak self] error in
            if error == nil { self?.isConnected = true }
        }

        // サーバーからのメッセージ受信ループ (接続維持目的)
        receiveLoop()
    }

    override func broadcastPaused() {}

    override func broadcastResumed() {}

    override func broadcastFinished() {
        webSocket?.send(.string(#"{"type":"leave"}"#)) { _ in }
        webSocket?.cancel(with: .goingAway, reason: nil)
    }

    // MARK: - Frame processing

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with type: RPSampleBufferType) {
        guard type == .video else { return }

        // フレームスキップ処理
        frameCounter += 1
        guard frameCounter % Config.frameSkip == 0 else { return }

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        autoreleasepool {
            guard let jpegData = encodeToJPEG(pixelBuffer: pixelBuffer) else { return }

            webSocket?.send(.data(jpegData)) { error in
                if let error = error {
                    print("[EchoShare] 送信エラー: \(error.localizedDescription)")
                }
            }
        }
    }

    // MARK: - JPEG エンコード

    private func encodeToJPEG(pixelBuffer: CVPixelBuffer) -> Data? {
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)

        // スケールダウン計算
        let origW = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
        let origH = CGFloat(CVPixelBufferGetHeight(pixelBuffer))
        let scaleX = min(Config.maxWidth  / origW, 1.0)
        let scaleY = min(Config.maxHeight / origH, 1.0)
        let scale  = min(scaleX, scaleY)

        let finalImage: CIImage
        if scale < 0.99 {
            finalImage = ciImage.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        } else {
            finalImage = ciImage
        }

        // JPEG 変換
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        return ciContext.jpegRepresentation(
            of: finalImage,
            colorSpace: colorSpace,
            options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: Config.jpegQuality]
        )
    }

    // MARK: - WebSocket 受信ループ (切断検知)

    private func receiveLoop() {
        webSocket?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success:
                self.receiveLoop()
            case .failure(let error):
                print("[EchoShare] 受信エラー: \(error.localizedDescription)")
                // 再接続は行わず、ユーザーが再度配信を開始する
            }
        }
    }

    // MARK: - Helpers

    private func readSetting(key: String) -> String? {
        let defaults = UserDefaults(suiteName: kAppGroupID)
        return defaults?.string(forKey: key)
    }

    private func makeError(_ message: String) -> NSError {
        return NSError(
            domain: "EchoShareBroadcast",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: message]
        )
    }
}
