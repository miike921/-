# EchoShare - エコー画像遠隔共有アプリ

GEエコー（Vscan Air等）の画像をリアルタイムで遠隔地の iPad に配信するシステムです。

---

## システム構成図

```
[ GEエコー ] ── Bluetooth/WiFi ──> [ 配信側 iPad ]
                                        │
                                  ReplayKit (画面録画)
                                        │
                                  EchoShareBroadcast Extension
                                        │
                                  JPEG 圧縮 → WebSocket
                                        │
                                [ 中継サーバー (Node.js) ]
                                        │
                                   WebSocket
                                        │
                                [ 視聴側 iPad ] ── JPEG 受信・表示
```

---

## 必要なもの

| 項目 | 内容 |
|------|------|
| 開発環境 | Mac + Xcode 15以上 |
| Apple Developer アカウント | $99/年 (App Store 配布 or TestFlight) |
| サーバー | Node.js が動くサーバー（以下参照） |
| iPad | iOS 16以上、2台 |

---

## セットアップ手順

### 1. 中継サーバーの構築

#### ローカルネットワーク（同一WiFi）の場合
Macで実行：
```bash
cd EchoShare/SignalingServer
npm install
node server.js
```
起動後、MacのIPアドレスをメモ（例: `192.168.1.100`）

#### インターネット経由（遠隔地）の場合
**Railway（無料枠あり）へデプロイ推奨：**

1. https://railway.app にアカウント作成
2. 「New Project」→「Deploy from GitHub repo」または「Empty Service」
3. `SignalingServer/` フォルダをアップロード
4. 自動的にサーバーURLが発行される（例: `wss://echoshare-xxxxx.railway.app`）

> 🔒 本番環境では必ず `wss://`（暗号化）を使用してください

---

### 2. iOS アプリの Xcode プロジェクト作成

#### 2-1. メインアプリの作成

1. Xcode を開く → 「Create a new Xcode project」
2. 「App」テンプレートを選択 → Next
3. 設定：
   - Product Name: `EchoShare`
   - Bundle Identifier: `com.yourname.EchoShare` ← **覚えておく**
   - Interface: SwiftUI
   - Language: Swift
4. 保存先を選択して作成

5. `iOS/EchoShare/` 内のSwiftファイルをすべてプロジェクトにドラッグ：
   - `EchoShareApp.swift`（既存の同名ファイルと置き換え）
   - `ContentView.swift`（置き換え）
   - `Models/AppModel.swift`
   - `Views/RoomSetupView.swift`
   - `Views/BroadcasterView.swift`
   - `Views/ViewerView.swift`
   - `Services/ViewerStreamingService.swift`

6. `Info.plist` の内容をXcodeのInfo設定に追加（またはファイルを置き換え）

#### 2-2. App Group の設定（重要）

1. プロジェクトナビゲーターでプロジェクトを選択
2. ターゲット「EchoShare」→「Signing & Capabilities」タブ
3. 「+ Capability」→「App Groups」を追加
4. 「+」ボタンで `group.com.yourname.EchoShare` を追加

#### 2-3. Broadcast Upload Extension の追加

1. メニュー「File」→「New」→「Target」
2. 「Broadcast Upload Extension」を選択 → Next
3. Product Name: `EchoShareBroadcast`
4. 「Activate」をクリック

5. 生成された `SampleHandler.swift` を `iOS/EchoShareBroadcast/SampleHandler.swift` で**置き換え**

6. Extension ターゲットにも App Group を追加：
   - ターゲット「EchoShareBroadcast」→「Signing & Capabilities」
   - 「App Groups」を追加 → 同じグループを選択

#### 2-4. Bundle ID の修正

以下のファイル内の Bundle ID プレースホルダーを実際の値に変更：

**`AppModel.swift`:**
```swift
let kAppGroupID = "group.com.yourname.EchoShare"  // ← 変更
```

**`SampleHandler.swift`:**
```swift
private let kAppGroupID = "group.com.yourname.EchoShare"  // ← 変更
```

**`BroadcasterView.swift`:**
```swift
BroadcastPickerRepresentable(
    preferredExtension: "com.yourname.EchoShare.EchoShareBroadcast"  // ← 変更
)
```

---

### 3. アプリのビルドと配布

**TestFlight 経由が最も簡単：**
1. Xcode → Product → Archive
2. App Store Connect にアップロード
3. TestFlight でテスターを招待
4. 両方の iPad にインストール

**または Ad-hoc 配布：**
1. 両 iPad の UDID を Apple Developer に登録
2. Ad-hoc プロビジョニングプロファイルで署名
3. Xcode から直接インストール

---

## 使い方

### 配信側 iPad（エコーを使用する側）

1. EchoShare アプリを開く
2. サーバーURL と ルームID を入力
3.「配信側」を選択
4. 「配信開始」ボタンをタップ
5. 「EchoShareBroadcast」を選択 →「配信を開始」
6. GE エコーアプリに切り替える
7. 配信中は画面上部に **赤いバー** が表示されます

### 視聴側 iPad（遠隔地）

1. EchoShare アプリを開く
2. **同じ** サーバーURL と ルームID を入力
3.「視聴側」を選択
4. 自動的に映像が表示されます

---

## 遅延の目安

| 条件 | 遅延 |
|------|------|
| 同一LAN内 | 約 200–500ms |
| インターネット経由（光回線） | 約 500ms–1.5秒 |
| LTE/5G | 約 1–3秒 |

医療教育・指導用途としては十分な遅延です。

---

## GEエコーアプリの画面キャプチャについて

⚠️ GEアプリがシステムのキャプチャを禁止している場合、**画面が黒くなって配信されます**。

**事前確認方法：**
1. GE エコーアプリでエコー画像を表示
2. iOS のコントロールセンターから「画面収録」を開始
3. 録画された動画を確認
   - **映像が録れていれば** EchoShare でも動作します
   - **黒い画面の場合** はキャプチャが禁止されています

キャプチャが禁止されている場合の代替案：
- Zoom / FaceTime / Teams の画面共有機能を使用
- GE に問い合わせてキャプチャ許可版の確認

---

## セキュリティについて

本アプリを医療現場で使用する場合：
- **必ずHTTPS/WSS（暗号化）** のサーバーを使用
- ルームIDは推測されにくい文字列を設定（例: `ward-echo-3b-2026`）
- 施設のネットワークポリシーに従う
- 患者個人を特定できる情報が映り込まないよう注意
- 利用前に患者の同意を取得する

---

## トラブルシューティング

| 症状 | 確認事項 |
|------|---------|
| 接続できない | サーバーURLが正しいか、サーバーが起動しているか |
| 黒い画面が配信される | GEアプリのキャプチャ制限（上記参照） |
| 映像が途切れる | ネットワーク環境の確認、`Config.jpegQuality` を下げる |
| EchoShareBroadcast が選択肢に出ない | Xcode でExtensionが正しくビルドされているか確認 |
| App Group エラー | Bundle ID と App Group ID が一致しているか確認 |

---

## ファイル構成

```
EchoShare/
├── SignalingServer/
│   ├── package.json          # Node.js 設定
│   └── server.js             # 中継サーバー本体
└── iOS/
    ├── EchoShare/            # メインアプリ (Xcodeプロジェクトに追加)
    │   ├── EchoShareApp.swift
    │   ├── ContentView.swift
    │   ├── Models/
    │   │   └── AppModel.swift       # 設定保存・App Group共有
    │   ├── Views/
    │   │   ├── RoomSetupView.swift  # 接続設定画面
    │   │   ├── BroadcasterView.swift# 配信側UI
    │   │   └── ViewerView.swift     # 視聴側UI
    │   ├── Services/
    │   │   └── ViewerStreamingService.swift  # WebSocket受信
    │   ├── Info.plist
    │   └── EchoShare.entitlements
    └── EchoShareBroadcast/   # Broadcast Upload Extension
        ├── SampleHandler.swift      # 画面キャプチャ・WebSocket送信
        ├── Info.plist
        └── EchoShareBroadcast.entitlements
```
