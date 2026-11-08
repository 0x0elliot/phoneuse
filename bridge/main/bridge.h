// Shared state of the bridge: what the screen shows and what status reports say.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define BRIDGE_FW "0.2.2"  // 0.2: TAP (0x0C); 0.2.1: the phone's Bluetooth signal in status; 0.2.2: activity icon
#define BRIDGE_NAME "PhoneUse Bridge"  // the name the iPhone sees in Bluetooth settings

typedef enum {
    ST_SETUP,    // waiting for phoneuse to connect over BLE
    ST_CODE,     // key exchanged: showing the code to compare
    ST_JOINING,  // joining the Wi-Fi network
    ST_ONLINE,   // on the network, taking commands
    ST_FAILED,   // the network didn't take the password, or isn't there
} bridge_state_t;

typedef struct {
    volatile bridge_state_t state;
    volatile bool setup_open;  // BLE setup advertising
    uint32_t code;
    char ip[16];
    char err[48];
    char phone[40];            // connected iPhone's name, or ""
    volatile bool phone_connected;
    volatile int wifi_rssi;
    volatile uint32_t reports, skipped;  // counters for status
    volatile int pending;                // reports handed to Bluetooth, not yet sent
    volatile uint32_t last_cmd_ms;       // when the PC last sent a valid packet
    volatile int battery_mv;
    char id[13];                         // hex MAC, the bridge's identity
    volatile int bt_rssi_delta;          // the phone's Bluetooth signal vs the golden range (0 = good, negative = weaker)
    volatile uint32_t bt_rssi_at_ms;     // when it was last measured (0: never)
    volatile uint8_t activity;           // the last input the PC sent: ACT_*
    volatile uint32_t activity_ms;       // when it came
} bridge_t;

// What the screen's activity icon shows, for ACT_SHOW_MS after the input.
enum { ACT_NONE, ACT_POINTER, ACT_TAP, ACT_KEYS };
#define ACT_SHOW_MS 600
void bridge_activity(int kind);  // screen.c: note input; wakes the screen only when the icon changes

extern bridge_t bridge;
void screen_update(void);  // redraw what changed (cheap to call often)
void screen_wake(void);    // full backlight again (it dims on battery when nothing happens)

// wifi.c
void wifi_init(void);
void wifi_join(const char *ssid, const char *pass);
// Change to another network; back to the current one if it doesn't work (err says why).
void wifi_switch(const char *ssid, const char *pass);
// Scan and write JSON [{"s":ssid,"r":rssi,"l":locked},...] into out. Blocks ~2 s.
int wifi_scan_json(char *out, int cap);

// setup_ble.c
void setup_ble_init(void);
void setup_ble_open(bool open);
void setup_ble_notify_info(void);

// hid.c
void hid_init(void);
// Send report `id` (1 keyboard, 2 mouse, 3 absolute, 4 consumer). skippable:
// refuse while earlier reports still wait. Returns 0 sent, 1 skipped, 2 no phone.
int hid_send(uint8_t id, const uint8_t *data, int len, bool skippable);
// Hover: keep only the newest; it goes out once Bluetooth is free. No answer.
void hid_latest(uint8_t id, const uint8_t *data, int len);
void hid_connect_last(void);
// Type keys: n (modifiers, usage) pairs, pressed and released in order on the
// bridge. Returns how many were queued; hid_keys_left() counts those not typed yet.
int hid_keys(const uint8_t *pairs, int n);
int hid_keys_left(void);
void hid_discoverable(int seconds);
void hid_read_signal(void);  // measure the phone's Bluetooth signal (bridge.bt_rssi_delta)
// A tap at the absolute position (x, y: 0..32767): press, hold hold_ms, release, all on
// the bridge. 0 queued, -1 not.
int hid_tap(uint16_t x, uint16_t y, uint16_t hold_ms);

// link.c
void link_start(void);
