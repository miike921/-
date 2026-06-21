import Foundation

// MARK: - App Group ID
// ⚠️ ここをご自身のBundle IDに合わせて変更してください
// 例: group.com.yourname.EchoShare
let kAppGroupID = "group.com.echoshare.EchoShare"

class AppModel: ObservableObject {

    // UserDefaults キー
    private enum Key {
        static let serverURL = "serverURL"
        static let roomId    = "roomId"
    }

    @Published var serverURL: String {
        didSet { save() }
    }

    @Published var roomId: String {
        didSet { save() }
    }

    init() {
        let defaults = UserDefaults(suiteName: kAppGroupID) ?? .standard
        serverURL = defaults.string(forKey: Key.serverURL) ?? "ws://your-server:8080"
        roomId    = defaults.string(forKey: Key.roomId)    ?? ""
    }

    private func save() {
        let defaults = UserDefaults(suiteName: kAppGroupID) ?? .standard
        defaults.set(serverURL, forKey: Key.serverURL)
        defaults.set(roomId,    forKey: Key.roomId)
    }
}
