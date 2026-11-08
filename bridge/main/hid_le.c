// Bluetooth LE HID device (HID over GATT): the iPhone pairs with "PhoneUse Bridge" and
// gets the same keyboard, mouse, absolute pointer and consumer keys as phoneuse's PC
// daemon (hid_daemon.py REPORT_MAP). It replaces hid.c (Bluetooth Classic) when
// BRIDGE_HID_LE is defined, with the same functions (bridge.h).
//
// The keyboard can be left out of the device's description (the HID report map)
// while the phone is connected: the bridge changes the report map and sends the
// phone a Service Changed indication, so iOS reads the map again without a
// reconnect. Without a keyboard, iOS keeps its own on-screen keyboard up (with
// AssistiveTouch's "Show Onscreen Keyboard"), so the owner can type by touch.
#ifdef BRIDGE_HID_LE
#include <stdio.h>
#include <string.h>

#include "bridge.h"
#include "esp_bt.h"
#include "esp_gap_ble_api.h"
#include "esp_gatt_common_api.h"
#include "esp_gatts_api.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

static const char *TAG = "hidle";

// The report map, in two parts: the keyboard collection, then everything else.
static const uint8_t map_keyboard[] = {
    // 1: keyboard
    0x05, 0x01, 0x09, 0x06, 0xa1, 0x01, 0x85, 0x01, 0x05, 0x07, 0x19, 0xe0, 0x29, 0xe7, 0x15, 0x00, 0x25, 0x01,
    0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x03, 0x95, 0x06, 0x75, 0x08, 0x15, 0x00,
    0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00, 0xc0,
};
static const uint8_t map_rest[] = {
    // 2: relative mouse with wheel
    0x05, 0x01, 0x09, 0x02, 0xa1, 0x01, 0x85, 0x02, 0x09, 0x01, 0xa1, 0x00, 0x05, 0x09, 0x19, 0x01, 0x29, 0x03,
    0x15, 0x00, 0x25, 0x01, 0x95, 0x03, 0x75, 0x01, 0x81, 0x02, 0x95, 0x01, 0x75, 0x05, 0x81, 0x03, 0x05, 0x01,
    0x09, 0x30, 0x09, 0x31, 0x09, 0x38, 0x15, 0x81, 0x25, 0x7f, 0x75, 0x08, 0x95, 0x03, 0x81, 0x06, 0xc0, 0xc0,
    // 3: absolute pointer, X and Y 0..32767
    0x05, 0x01, 0x09, 0x02, 0xa1, 0x01, 0x85, 0x03, 0x09, 0x01, 0xa1, 0x00, 0x05, 0x09, 0x19, 0x01, 0x29, 0x03,
    0x15, 0x00, 0x25, 0x01, 0x95, 0x03, 0x75, 0x01, 0x81, 0x02, 0x95, 0x01, 0x75, 0x05, 0x81, 0x03, 0x05, 0x01,
    0x09, 0x30, 0x09, 0x31, 0x15, 0x00, 0x26, 0xff, 0x7f, 0x75, 0x10, 0x95, 0x02, 0x81, 0x02, 0xc0, 0xc0,
    // 4: consumer keys: Eject, Voice Command (Siri), Menu (Home), AC Search
    0x05, 0x0c, 0x09, 0x01, 0xa1, 0x01, 0x85, 0x04, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x01,
    0x09, 0xb8, 0x81, 0x02, 0x09, 0xcf, 0x81, 0x02, 0x09, 0x40, 0x81, 0x02, 0x0a, 0x21, 0x02, 0x81, 0x02,
    0x95, 0x04, 0x81, 0x03, 0xc0,
};
static uint8_t map_now[sizeof map_keyboard + sizeof map_rest];
static uint16_t map_len;
static volatile bool keyboard_on = true;

// ---- the GATT database: HID service, battery, device information ----
static const uint16_t PRIMARY = ESP_GATT_UUID_PRI_SERVICE, CHAR_DECL = ESP_GATT_UUID_CHAR_DECLARE,
                      CCC = ESP_GATT_UUID_CHAR_CLIENT_CONFIG, U_HID = 0x1812, U_INFO = 0x2A4A, U_MAP = 0x2A4B,
                      U_CTRL = 0x2A4C, U_REPORT = 0x2A4D, U_PROTO = 0x2A4E, U_REF = 0x2908, U_BAT = 0x180F,
                      U_LEVEL = 0x2A19, U_DIS = 0x180A, U_PNP = 0x2A50;
static const uint8_t P_READ = ESP_GATT_CHAR_PROP_BIT_READ,
                     P_READ_NOTIFY = ESP_GATT_CHAR_PROP_BIT_READ | ESP_GATT_CHAR_PROP_BIT_NOTIFY,
                     P_WRITE_NR = ESP_GATT_CHAR_PROP_BIT_WRITE_NR,
                     P_READ_WRITE_NR = ESP_GATT_CHAR_PROP_BIT_READ | ESP_GATT_CHAR_PROP_BIT_WRITE_NR;
#define ENC_R ESP_GATT_PERM_READ_ENCRYPTED
#define ENC_RW (ESP_GATT_PERM_READ_ENCRYPTED | ESP_GATT_PERM_WRITE_ENCRYPTED)

enum {
    H_SVC, H_INFO_C, H_INFO_V, H_MAP_C, H_MAP_V, H_CTRL_C, H_CTRL_V, H_PROTO_C, H_PROTO_V,
    H_R1_C, H_R1_V, H_R1_CCC, H_R1_REF, H_R2_C, H_R2_V, H_R2_CCC, H_R2_REF,
    H_R3_C, H_R3_V, H_R3_CCC, H_R3_REF, H_R4_C, H_R4_V, H_R4_CCC, H_R4_REF, H_N
};
enum { B_SVC, B_LEVEL_C, B_LEVEL_V, B_LEVEL_CCC, B_N };
enum { D_SVC, D_PNP_C, D_PNP_V, D_N };

static uint8_t hid_info[4] = {0x11, 0x01, 0x00, 0x02};  // HID 1.11, no country, normally connectable
static uint8_t ctrl_v[1], proto_v[1] = {1};               // report protocol
static uint8_t r1[8], r2[4], r3[5], r4[1];
static uint8_t ccc[4][2], bat_ccc[2], level[1] = {100};
static uint8_t ref1[2] = {1, 1}, ref2[2] = {2, 1}, ref3[2] = {3, 1}, ref4[2] = {4, 1};  // (id, input)
static uint8_t pnp[7] = {0x02, 0x3a, 0x30, 0x01, 0x40, 0x00, 0x01};  // USB VID 0x303A (Espressif), PID 0x4001

#define DECL(prop) {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&CHAR_DECL, ESP_GATT_PERM_READ, 1, 1, (uint8_t *)&prop}}
#define ATTR(uuid, perm, max, len, v) {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&uuid, perm, max, len, (uint8_t *)v}}
#define REPORT(n, v, c, ref)                                          \
    [H_R##n##_C] = DECL(P_READ_NOTIFY),                               \
    [H_R##n##_V] = ATTR(U_REPORT, ENC_R, sizeof v, sizeof v, v),      \
    [H_R##n##_CCC] = ATTR(CCC, ENC_RW, 2, 2, c),                      \
    [H_R##n##_REF] = ATTR(U_REF, ENC_R, 2, 2, ref)

static esp_gatts_attr_db_t hid_db[H_N] = {
    [H_SVC] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&PRIMARY, ESP_GATT_PERM_READ, 2, 2, (uint8_t *)&U_HID}},
    [H_INFO_C] = DECL(P_READ),
    [H_INFO_V] = ATTR(U_INFO, ENC_R, 4, 4, hid_info),
    [H_MAP_C] = DECL(P_READ),
    [H_MAP_V] = ATTR(U_MAP, ENC_R, sizeof map_now, 0, map_now),  // length set at start
    [H_CTRL_C] = DECL(P_WRITE_NR),
    [H_CTRL_V] = ATTR(U_CTRL, ENC_RW, 1, 1, ctrl_v),
    [H_PROTO_C] = DECL(P_READ_WRITE_NR),
    [H_PROTO_V] = ATTR(U_PROTO, ENC_RW, 1, 1, proto_v),
    REPORT(1, r1, ccc[0], ref1),
    REPORT(2, r2, ccc[1], ref2),
    REPORT(3, r3, ccc[2], ref3),
    REPORT(4, r4, ccc[3], ref4),
};
static const esp_gatts_attr_db_t bat_db[B_N] = {
    [B_SVC] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&PRIMARY, ESP_GATT_PERM_READ, 2, 2, (uint8_t *)&U_BAT}},
    [B_LEVEL_C] = DECL(P_READ_NOTIFY),
    [B_LEVEL_V] = ATTR(U_LEVEL, ENC_R, 1, 1, level),
    [B_LEVEL_CCC] = ATTR(CCC, ENC_RW, 2, 2, bat_ccc),
};
static const esp_gatts_attr_db_t dis_db[D_N] = {
    [D_SVC] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&PRIMARY, ESP_GATT_PERM_READ, 2, 2, (uint8_t *)&U_DIS}},
    [D_PNP_C] = DECL(P_READ),
    [D_PNP_V] = ATTR(U_PNP, ESP_GATT_PERM_READ, 7, 7, pnp),
};

#define HID_APP 0x48
static uint16_t h[H_N];
static esp_gatt_if_t gif = ESP_GATT_IF_NONE;
static uint16_t phone_conn = 0xFFFF;  // the bonded phone's connection
static esp_bd_addr_t phone_bda;
static volatile bool congested;
static const uint16_t report_handle_index[5] = {0, H_R1_V, H_R2_V, H_R3_V, H_R4_V};
// This app's open connections (the phone, and the PC during setup): id and address.
static struct { uint16_t id; esp_bd_addr_t bda; bool used; } conns[4];
static int last_conn = -1;

// ---- advertising: HID while no phone is connected, setup while setup is open ----
static uint8_t hid_uuid128[16] = {0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80,
                                  0x00, 0x10, 0x00, 0x00, 0x12, 0x18, 0x00, 0x00};
static esp_ble_adv_params_t hid_adv = {
    .adv_int_min = 0x20, .adv_int_max = 0x40, .adv_type = ADV_TYPE_IND, .own_addr_type = BLE_ADDR_TYPE_PUBLIC,
    .channel_map = ADV_CHNL_ALL, .adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY,
};
static int adv_mode = -1, adv_pending;  // 0 off, 1 HID, 2 setup

void ble_adv_refresh(void) {
    int want = bridge.setup_open ? 2 : (phone_conn == 0xFFFF ? 1 : 0);
    if (want == adv_mode) return;
    esp_ble_gap_stop_advertising();
    adv_mode = want;
    if (want == 1) {
        esp_ble_gap_set_device_name(BRIDGE_NAME);
        esp_ble_adv_data_t ad = {.set_scan_rsp = false, .include_name = true, .appearance = 0x03C0,
                                 .service_uuid_len = 16, .p_service_uuid = hid_uuid128,
                                 .flag = ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT};
        adv_pending = 1;
        esp_ble_gap_config_adv_data(&ad);
    } else if (want == 2) {
        adv_pending = 2;
        setup_ble_config_adv();  // sets the setup name, data and scan response
    }
}

static void start_adv(void) {
    if (adv_mode == 1) esp_ble_gap_start_advertising(&hid_adv);
    else if (adv_mode == 2) setup_ble_start_adv();
}

// ---- reports ----
// Reports handed to Bluedroid that it hasn't sent yet (ESP_GATTS_CONF_EVT counts them
// down): hovers wait for zero, so the pointer never lags behind a queue.
static volatile int in_lower;
static volatile uint32_t in_lower_since;

static int send_report(uint8_t id, const uint8_t *data, int len) {
    if (id < 1 || id > 4 || phone_conn == 0xFFFF || gif == ESP_GATT_IF_NONE) return 2;
    if (id == 1 && !keyboard_on) return 2;
    in_lower++;
    in_lower_since = xTaskGetTickCount();
    if (esp_ble_gatts_send_indicate(gif, phone_conn, h[report_handle_index[id]], len, (uint8_t *)data, false) != ESP_OK) {
        in_lower--;
        return 2;
    }
    bridge.reports++;
    bridge.pending = in_lower;
    return 0;
}

// Busy while a report still waits in the link's queue: ESP_GATTS_CONF_EVT only says a
// notification reached that queue, so ask the stack how much of it is free. One report
// waits at most, so a hover is never more than one connection interval old.
static bool busy(void) {
    if (congested) return true;
    if (phone_conn == 0xFFFF) return false;
    uint16_t total = esp_ble_get_sendable_packets_num(), free_ = esp_ble_get_cur_sendable_packets_num(phone_conn);
    return total > free_;
}

// Typing: the PC sends a whole string's keys in one packet; this task presses and
// releases each at Bluetooth pace, with no Wi-Fi round trip per key.
static QueueHandle_t keyq;
static uint8_t latest_id, latest[8], latest_len;
static volatile bool latest_set;
static portMUX_TYPE latest_mux = portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t out_task;

static void out_loop(void *arg) {
    for (;;) {
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(20));
        if (!latest_set || phone_conn == 0xFFFF || busy()) continue;
        uint8_t id, buf[8], n;
        portENTER_CRITICAL(&latest_mux);
        id = latest_id, n = latest_len;
        memcpy(buf, latest, n);
        latest_set = false;
        portEXIT_CRITICAL(&latest_mux);
        send_report(id, buf, n);
    }
}

static void key_loop(void *arg) {
    uint8_t k[2];
    for (;;) {
        xQueueReceive(keyq, k, portMAX_DELAY);
        uint8_t down[8] = {k[0], 0, k[1], 0, 0, 0, 0, 0}, up[8] = {0};
        for (int i = 0; i < 100 && phone_conn != 0xFFFF && (busy() || send_report(1, down, 8) != 0); i++)
            vTaskDelay(1);
        vTaskDelay(pdMS_TO_TICKS(12));
        send_report(1, up, 8);
        vTaskDelay(pdMS_TO_TICKS(12));
    }
}

int hid_send(uint8_t id, const uint8_t *data, int len, bool skippable) {
    if (phone_conn == 0xFFFF) return 2;
    if (skippable && busy()) {
        bridge.skipped++;
        return 1;
    }
    return send_report(id, data, len);
}

void hid_latest(uint8_t id, const uint8_t *data, int len) {
    if (len > 8) return;
    portENTER_CRITICAL(&latest_mux);
    if (latest_set) bridge.skipped++;
    latest_id = id, latest_len = len;
    memcpy(latest, data, len);
    latest_set = true;
    portEXIT_CRITICAL(&latest_mux);
    xTaskNotifyGive(out_task);
}

int hid_keys(const uint8_t *pairs, int n) {
    int queued = 0;
    for (int i = 0; i < n; i++)
        if (xQueueSend(keyq, pairs + 2 * i, 0) == pdTRUE) queued++;
    return queued;
}

int hid_keys_left(void) { return keyq ? uxQueueMessagesWaiting(keyq) : 0; }

// LE: a bonded phone reconnects by itself when the bridge advertises.
void hid_connect_last(void) { ble_adv_refresh(); }
void hid_discoverable(int seconds) { ble_adv_refresh(); }

// ---- the keyboard in or out of the report map ----
static void build_map(void) {
    map_len = 0;
    if (keyboard_on) {
        memcpy(map_now, map_keyboard, sizeof map_keyboard);
        map_len = sizeof map_keyboard;
    }
    memcpy(map_now + map_len, map_rest, sizeof map_rest);
    map_len += sizeof map_rest;
}

int hid_set_keyboard(bool on) {
    if (on == keyboard_on) return 0;
    keyboard_on = on;
    build_map();
    if (h[H_MAP_V]) esp_ble_gatts_set_attr_value(h[H_MAP_V], map_len, map_now);
    if (phone_conn == 0xFFFF) return 0;
    // Tell the phone the services changed: iOS discovers them again and reads the map.
    esp_err_t e = esp_ble_gatts_send_service_change_indication(gif, phone_bda);
    ESP_LOGI(TAG, "keyboard %s: service changed sent (%d)", on ? "on" : "off", e);
    return e == ESP_OK ? 0 : -1;
}

bool hid_keyboard_on(void) { return keyboard_on; }

// ---- events (setup_ble.c forwards every GATT and GAP event here first) ----
bool hid_le_gatts_event(esp_gatts_cb_event_t ev, esp_gatt_if_t g, esp_ble_gatts_cb_param_t *p) {
    if (ev == ESP_GATTS_REG_EVT) {
        if (p->reg.app_id != HID_APP) return false;
        gif = g;
        esp_ble_gatts_create_attr_tab(hid_db, g, H_N, 0);
        esp_ble_gatts_create_attr_tab(bat_db, g, B_N, 1);
        esp_ble_gatts_create_attr_tab(dis_db, g, D_N, 2);
        return true;
    }
    if (g != gif) {  // the setup service's events; connection events go to both
        if (ev == ESP_GATTS_DISCONNECT_EVT && p->disconnect.conn_id == phone_conn) goto lost;
        return false;
    }
    switch (ev) {
    case ESP_GATTS_CREAT_ATTR_TAB_EVT:
        if (p->add_attr_tab.status != ESP_GATT_OK) {
            ESP_LOGE(TAG, "attribute table: %d", p->add_attr_tab.status);
            break;
        }
        if (p->add_attr_tab.num_handle == H_N) {
            memcpy(h, p->add_attr_tab.handles, sizeof h);
            esp_ble_gatts_set_attr_value(h[H_MAP_V], map_len, map_now);
        }
        esp_ble_gatts_start_service(p->add_attr_tab.handles[0]);
        if (p->add_attr_tab.num_handle == D_N) ble_adv_refresh();  // the last table: start advertising
        break;
    case ESP_GATTS_CONNECT_EVT:  // the phone is known once it encrypts with its bond (ESP_GAP_BLE_AUTH_CMPL_EVT)
        for (int i = 0; i < 4; i++)
            if (!conns[i].used) {
                conns[i].used = true, conns[i].id = p->connect.conn_id, last_conn = i;
                memcpy(conns[i].bda, p->connect.remote_bda, sizeof(esp_bd_addr_t));
                break;
            }
        break;
    case ESP_GATTS_DISCONNECT_EVT:
        for (int i = 0; i < 4; i++)
            if (conns[i].used && conns[i].id == p->disconnect.conn_id) conns[i].used = false;
        if (p->disconnect.conn_id == phone_conn) goto lost;
        break;
    case ESP_GATTS_CONF_EVT:  // a notification went out
        if (in_lower > 0) in_lower--;
        bridge.pending = in_lower;
        if (latest_set && out_task) xTaskNotifyGive(out_task);
        break;
    case ESP_GATTS_CONGEST_EVT:
        congested = p->congest.congested;
        if (!congested && latest_set && out_task) xTaskNotifyGive(out_task);
        break;
    default:
        break;
    }
    return false;  // connection events also matter to setup_ble.c
lost:
    phone_conn = 0xFFFF;
    in_lower = 0;
    bridge.phone_connected = false;
    congested = false;
    ble_adv_refresh();
    screen_update();
    return false;
}

void hid_le_gap_event(esp_gap_ble_cb_event_t ev, esp_ble_gap_cb_param_t *p) {
    switch (ev) {
    case ESP_GAP_BLE_ADV_DATA_SET_COMPLETE_EVT:
    case ESP_GAP_BLE_SCAN_RSP_DATA_SET_COMPLETE_EVT:
        if (adv_pending > 0 && --adv_pending == 0) start_adv();
        break;
    case ESP_GAP_BLE_UPDATE_CONN_PARAMS_EVT:
        ESP_LOGI(TAG, "connection: interval %.2f ms, latency %d, timeout %d ms (status %d)",
                 p->update_conn_params.conn_int * 1.25, p->update_conn_params.latency,
                 p->update_conn_params.timeout * 10, p->update_conn_params.status);
        bridge.conn_interval_x100 = p->update_conn_params.conn_int * 125;
        break;
    case ESP_GAP_BLE_SEC_REQ_EVT:
        esp_ble_gap_security_rsp(p->ble_security.ble_req.bd_addr, true);
        break;
    case ESP_GAP_BLE_AUTH_CMPL_EVT: {
        esp_ble_auth_cmpl_t *a = &p->ble_security.auth_cmpl;
        ESP_LOGI(TAG, "auth with %02x:%02x:%02x:%02x:%02x:%02x: %s", a->bd_addr[0], a->bd_addr[1], a->bd_addr[2],
                 a->bd_addr[3], a->bd_addr[4], a->bd_addr[5], a->success ? "ok" : "failed");
        if (!a->success) break;
        // The phone: the peer that encrypted with a bond. Its connection is the one with
        // that address, or else the newest (iOS connects from a private address).
        int k = -1;
        for (int i = 0; i < 4; i++)
            if (conns[i].used && !memcmp(conns[i].bda, a->bd_addr, sizeof(esp_bd_addr_t))) k = i;
        if (k < 0) k = last_conn;
        if (k < 0 || !conns[k].used) break;
        memcpy(phone_bda, conns[k].bda, sizeof phone_bda);
        phone_conn = conns[k].id;
        bridge.phone_connected = true;
        snprintf(bridge.phone, sizeof bridge.phone, "iPhone %02x:%02x", a->bd_addr[4], a->bd_addr[5]);
        // 11.25 ms: the shortest interval iOS grants an HID accessory
        esp_ble_conn_update_params_t cp = {.min_int = 9, .max_int = 9, .latency = 0, .timeout = 400};
        memcpy(cp.bda, phone_bda, sizeof cp.bda);
        esp_ble_gap_update_conn_params(&cp);
        ble_adv_refresh();
        screen_update();
        break;
    }
    default:
        break;
    }
}

void hid_init(void) {
    build_map();
    esp_ble_auth_req_t auth = ESP_LE_AUTH_REQ_SC_BOND;
    esp_ble_io_cap_t io = ESP_IO_CAP_NONE;
    uint8_t keysize = 16, ikey = ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK, rkey = ikey;
    esp_ble_gap_set_security_param(ESP_BLE_SM_AUTHEN_REQ_MODE, &auth, 1);
    esp_ble_gap_set_security_param(ESP_BLE_SM_IOCAP_MODE, &io, 1);
    esp_ble_gap_set_security_param(ESP_BLE_SM_MAX_KEY_SIZE, &keysize, 1);
    esp_ble_gap_set_security_param(ESP_BLE_SM_SET_INIT_KEY, &ikey, 1);
    esp_ble_gap_set_security_param(ESP_BLE_SM_SET_RSP_KEY, &rkey, 1);
    esp_ble_gatts_app_register(HID_APP);
    keyq = xQueueCreate(512, 2);
    xTaskCreatePinnedToCore(out_loop, "hidout", 3072, NULL, 19, &out_task, 0);
    xTaskCreatePinnedToCore(key_loop, "keys", 3072, NULL, 18, NULL, 0);
}
#endif
