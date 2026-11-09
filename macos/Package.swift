// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "phoneuse-mac",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "phoneuse-mac",
            path: "Sources/phoneuse-mac"
        )
    ]
)
