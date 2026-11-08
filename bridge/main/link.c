// UDP control link on port 47700. phoneuse sends HID reports; the bridge answers
// each one at once with what happened, so the sender can carry skipped motion.
//
// Packet: "PU" ver(1) type(1) session(u32 LE) seq(u32 LE) body mac(8)
//   mac = HMAC-SHA256(control key, everything before it), first 8 bytes.
// Only FIND and its answer go unsigned (they carry no secrets).
//
//   0x10 FIND                 -> 0x90 {"id","name","fw","ip"}       (broadcast ok)
//   0x01 HELLO  nonce(8)      -> 0x81 nonce(8), session = a new random id
//   0x02 REPORT flags id data -> 0x82 result(0 sent, 1 skipped, 2 no phone) waiting
//        flags bit 0: skippable (motion and hovers; never keys or buttons)
//   0x03 STATUS               -> 0x83 JSON
//   0x04 CONNECT              -> 0x84 (page the last iPhone)
//   0x05 SETUP                -> 0x85 (open BLE setup again, to change network)
// Packets after HELLO carry its session and a rising seq; an old seq is dropped,
// the same seq again gets the same answer again (a lost reply), nothing is redone.
#include <stdio.h>
#include <string.h>

#include "bridge.h"
#include "settings.h"
#include "crypto.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"

#define PORT 47700
#define HDR 12
#define MAC 8

static const char *TAG = "link";
static uint32_t session, last_seq;
static uint8_t last_reply[300];
static int last_reply_len;

static bool mac_ok(const uint8_t *b, int n) {
    uint8_t m[32];
    crypto_hmac(settings.key, b, n - MAC, m);
    uint8_t d = 0;
    for (int i = 0; i < MAC; i++) d |= m[i] ^ b[n - MAC + i];
    return d == 0;
}

static int reply(uint8_t *out, uint8_t type, uint32_t sid, uint32_t seq, const void *body, int bn, bool sign) {
    out[0] = 'P', out[1] = 'U', out[2] = 1, out[3] = type;
    memcpy(out + 4, &sid, 4);
    memcpy(out + 8, &seq, 4);
    memcpy(out + HDR, body, bn);
    int n = HDR + bn;
    if (sign) {
        uint8_t m[32];
        crypto_hmac(settings.key, out, n, m);
        memcpy(out + n, m, MAC);
        n += MAC;
    }
    return n;
}

static int status_json(char *j, int cap) {
    return snprintf(j, cap,
                    "{\"id\":\"%s\",\"fw\":\"%s\",\"phone\":\"%s\",\"connected\":%s,\"rssi\":%d,\"reports\":%lu,"
                    "\"skipped\":%lu,\"waiting\":%d,\"battery_mv\":%d,\"uptime\":%llu,\"ssid\":\"%s\"}",
                    bridge.id, BRIDGE_FW, bridge.phone, bridge.phone_connected ? "true" : "false", bridge.wifi_rssi,
                    (unsigned long)bridge.reports, (unsigned long)bridge.skipped, bridge.pending, bridge.battery_mv,
                    (unsigned long long)(esp_timer_get_time() / 1000000), settings.ssid);
}

static void link_task(void *arg) {
    int s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(PORT), .sin_addr.s_addr = htonl(INADDR_ANY)};
    bind(s, (struct sockaddr *)&a, sizeof a);
    uint8_t in[300], out[300];
    for (;;) {
        struct sockaddr_in from;
        socklen_t fl = sizeof from;
        int n = recvfrom(s, in, sizeof in, 0, (struct sockaddr *)&from, &fl);
        if (n < HDR || in[0] != 'P' || in[1] != 'U' || in[2] != 1) continue;
        uint8_t type = in[3];
        uint32_t sid, seq;
        memcpy(&sid, in + 4, 4);
        memcpy(&seq, in + 8, 4);
        int m = 0;
        if (type == 0x10) {  // FIND
            char j[160];
            int jn = snprintf(j, sizeof j, "{\"id\":\"%s\",\"name\":\"%s\",\"fw\":\"%s\",\"ip\":\"%s\"}", bridge.id,
                              BRIDGE_NAME, BRIDGE_FW, bridge.ip);
            m = reply(out, 0x90, 0, 0, j, jn, false);
            sendto(s, out, m, 0, (struct sockaddr *)&from, fl);
            continue;
        }
        if (!settings.configured || n < HDR + MAC || !mac_ok(in, n)) continue;
        const uint8_t *body = in + HDR;
        int bn = n - HDR - MAC;
        if (type == 0x01) {  // HELLO
            if (bn != 8) continue;
            crypto_random(&session, 4);
            last_seq = 0;
            last_reply_len = 0;
            m = reply(out, 0x81, session, 0, body, 8, true);
            sendto(s, out, m, 0, (struct sockaddr *)&from, fl);
            continue;
        }
        if (sid != session || !session) continue;
        if (seq == last_seq && last_reply_len) {  // the reply got lost: same answer, no redo
            sendto(s, last_reply, last_reply_len, 0, (struct sockaddr *)&from, fl);
            continue;
        }
        if (seq < last_seq) continue;
        last_seq = seq;
        bridge.last_cmd_ms = esp_timer_get_time() / 1000;
        if (type == 0x02 && bn >= 2) {  // REPORT
            uint8_t r[2];
            r[0] = hid_send(body[1], body + 2, bn - 2, body[0] & 1);
            r[1] = bridge.pending;
            m = reply(out, 0x82, sid, seq, r, 2, true);
        } else if (type == 0x03) {
            char j[256];
            m = reply(out, 0x83, sid, seq, j, status_json(j, sizeof j), true);
        } else if (type == 0x04) {
            hid_connect_last();
            m = reply(out, 0x84, sid, seq, "", 0, true);
        } else if (type == 0x05) {
            setup_ble_open(true);
            m = reply(out, 0x85, sid, seq, "", 0, true);
        } else {
            continue;
        }
        memcpy(last_reply, out, m);
        last_reply_len = m;
        sendto(s, out, m, 0, (struct sockaddr *)&from, fl);
    }
}

void link_start(void) {
    ESP_LOGI(TAG, "listening on udp %d", PORT);
    xTaskCreatePinnedToCore(link_task, "link", 6144, NULL, 18, NULL, 1);
}
