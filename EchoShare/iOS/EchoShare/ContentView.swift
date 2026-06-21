import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appModel: AppModel

    var body: some View {
        NavigationView {
            RoomSetupView()
        }
        .navigationViewStyle(.stack)
    }
}
