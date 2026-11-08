import Foundation
import Network

enum CompanionError: LocalizedError {
    case notPaired
    case unreachable
    case server(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired: "The app isn't paired with a PC."
        case .unreachable: "The PC isn't reachable."
        case .server(_, let message): message
        }
    }
}

/// Sends signed requests to the PC's companion API. When the saved address doesn't answer, it looks the PC up
/// over Bonjour by its id, saves the new address, and tries once more.
struct CompanionClient {
    var pairing: Pairing

    static func paired() throws -> CompanionClient {
        guard let p = PairingStore.load() else { throw CompanionError.notPaired }
        return CompanionClient(pairing: p)
    }

    @discardableResult
    func send(_ method: String, _ path: String, json: [String: Any]? = nil, timeout: TimeInterval = 6) async throws -> Data {
        let body = try json.map { try JSONSerialization.data(withJSONObject: $0, options: [.sortedKeys]) } ?? Data()
        do {
            return try await attempt(method, path, body: body, host: pairing.host, port: pairing.port, timeout: timeout)
        } catch CompanionError.unreachable {
            guard let found = await BonjourLookup.find(id: pairing.id),
                  found.host != pairing.host || found.port != pairing.port else { throw CompanionError.unreachable }
            PairingStore.updateAddress(host: found.host, port: found.port)
            return try await attempt(method, path, body: body, host: found.host, port: found.port, timeout: timeout)
        }
    }

    func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        try JSONDecoder().decode(T.self, from: await send("GET", path))
    }

    private func attempt(_ method: String, _ path: String, body: Data, host: String, port: Int,
                         timeout: TimeInterval) async throws -> Data {
        let hostPart = host.contains(":") ? "[\(host)]" : host
        guard let url = URL(string: "http://\(hostPart):\(port)\(path)") else { throw CompanionError.unreachable }
        var req = URLRequest(url: url, timeoutInterval: timeout)
        req.httpMethod = method
        let time = String(Int(Date().timeIntervalSince1970))
        let nonce = CompanionCrypto.randomNonceHex()
        req.setValue(time, forHTTPHeaderField: "X-PU-Time")
        req.setValue(nonce, forHTTPHeaderField: "X-PU-Nonce")
        req.setValue(CompanionCrypto.signature(key: pairing.key, method: method, path: path, time: time,
                                               nonce: nonce, body: body), forHTTPHeaderField: "X-PU-Sig")
        if !body.isEmpty {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let data: Data, response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: req)
        } catch {
            throw CompanionError.unreachable
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let message = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
        guard (200..<300).contains(status), message == nil else {
            throw CompanionError.server(status: status, message: message ?? "The PC answered \(status).")
        }
        return data
    }
}

/// Finds the PC's current address over Bonjour (_phoneuse._tcp, TXT id).
final class BonjourLookup: @unchecked Sendable {
    // Everything below runs on `queue`.
    private let queue = DispatchQueue(label: "co.lxe.phoneuse.bonjour")
    private let browser = NWBrowser(for: .bonjourWithTXTRecord(type: "_phoneuse._tcp", domain: nil), using: .tcp)
    private var connection: NWConnection?
    private var done: ((host: String, port: Int)?) -> Void = { _ in }

    static func find(id: String, timeout: TimeInterval = 4) async -> (host: String, port: Int)? {
        let lookup = BonjourLookup()
        return await withCheckedContinuation { cont in
            lookup.queue.async { lookup.start(id: id, timeout: timeout) { cont.resume(returning: $0) } }
        }
    }

    private func start(id: String, timeout: TimeInterval, then: @escaping ((host: String, port: Int)?) -> Void) {
        done = then
        browser.browseResultsChangedHandler = { [self] results, _ in
            guard connection == nil, let match = results.first(where: {
                if case .bonjour(let txt) = $0.metadata { return txt["id"] == id }
                return false
            }) else { return }
            // Connecting resolves the service to an address and port.
            let c = NWConnection(to: match.endpoint, using: .tcp)
            connection = c
            c.stateUpdateHandler = { [self] state in
                guard case .ready = state, case .hostPort(let host, let port)? = c.currentPath?.remoteEndpoint
                else { return }
                var text = "\(host)"
                if let pct = text.firstIndex(of: "%") { text = String(text[..<pct]) }
                finish((text, Int(port.rawValue)))
            }
            c.start(queue: queue)
        }
        browser.start(queue: queue)
        queue.asyncAfter(deadline: .now() + timeout) { [self] in finish(nil) }
    }

    private func finish(_ result: (host: String, port: Int)?) {
        let then = done
        done = { _ in }
        browser.cancel()
        connection?.cancel()
        then(result)
    }
}
