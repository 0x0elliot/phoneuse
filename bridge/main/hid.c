// Bluetooth Classic HID device: the iPhone pairs with "PhoneUse" and gets the same
// keyboard, mouse, absolute pointer and consumer keys as phoneuse's PC daemon
// (hid_daemon.py REPORT_MAP, kept byte-identical).
#include <stdio.h>
#include <string.h>

#include "bridge.h"
#include "esp_bt.h"
#include "esp_bt_device.h"
#include "esp_gap_bt_api.h"
#include "esp_hidd_api.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

static const char *TAG = "hid";

static uint8_t report_map[] = {
    // 1: keyboard
    0x05, 0x01, 0x09, 0x06, 0xa1, 0x01, 0x85, 0x01, 0x05, 0x07, 0x19, 0xe0, 0x29, 0xe7, 0x15, 0x00, 0x25, 0x01,
    0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x03, 0x95, 0x06, 0x75, 0x08, 0x15, 0x00,
    0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00, 0xc0,
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

static esp_hidd_app_param_t app = {
    .name = BRIDGE_NAME, .description = "Mouse and keyboard", .provider = "phoneuse",
    .subclass = ESP_HID_CLASS_COM, .desc_list = report_map, .desc_list_len = sizeof report_map,
};
static esp_hidd_qos_param_t qos;
static esp_bd_addr_t peer;
static volatile int in_lower;  // reports handed to Bluedroid that it hasn't sent on yet

static void name_from(const uint8_t *addr) { esp_bt_gap_read_remote_name((uint8_t *)addr); }

static void hidd_cb(esp_hidd_cb_event_t ev, esp_hidd_cb_param_t *p) {
    switch (ev) {
    case ESP_HIDD_INIT_EVT:
        esp_bt_hid_device_register_app(&app, &qos, &qos);
        break;
    case ESP_HIDD_REGISTER_APP_EVT:
        esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_GENERAL_DISCOVERABLE);
        hid_connect_last();
        break;
    case ESP_HIDD_OPEN_EVT:
        if (p->open.conn_status == ESP_HIDD_CONN_STATE_CONNECTED) {
            memcpy(peer, p->open.bd_addr, sizeof peer);
            bridge.phone_connected = true;
            in_lower = 0;
            snprintf(bridge.phone, sizeof bridge.phone, "%02x:%02x:%02x:%02x:%02x:%02x", peer[0], peer[1], peer[2],
                     peer[3], peer[4], peer[5]);
            name_from(peer);
            // Connected: stay connectable for a reconnect, hidden from new pairings.
            esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_NON_DISCOVERABLE);
            screen_update();
        }
        break;
    case ESP_HIDD_CLOSE_EVT:
        if (p->close.conn_status == ESP_HIDD_CONN_STATE_DISCONNECTED) {
            bridge.phone_connected = false;
            in_lower = 0;
            esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_GENERAL_DISCOVERABLE);
            screen_update();
        }
        break;
    case ESP_HIDD_SEND_REPORT_EVT:
        if (in_lower > 0) in_lower--;
        break;
    default:
        break;
    }
}

static void gap_cb(esp_bt_gap_cb_event_t ev, esp_bt_gap_cb_param_t *p) {
    switch (ev) {
    case ESP_BT_GAP_CFM_REQ_EVT:  // Just Works pairing: accept (the person starts it on the phone)
        esp_bt_gap_ssp_confirm_reply(p->cfm_req.bda, true);
        break;
    case ESP_BT_GAP_AUTH_CMPL_EVT:
        ESP_LOGI(TAG, "paired with %s: %d", p->auth_cmpl.device_name, p->auth_cmpl.stat);
        break;
    case ESP_BT_GAP_READ_REMOTE_NAME_EVT:
        if (p->read_rmt_name.stat == ESP_BT_STATUS_SUCCESS) {
            snprintf(bridge.phone, sizeof bridge.phone, "%s", (char *)p->read_rmt_name.rmt_name);
            screen_update();
        }
        break;
    default:
        break;
    }
}

void hid_init(void) {
    esp_bt_gap_register_callback(gap_cb);
    esp_bt_gap_set_device_name(BRIDGE_NAME);
    esp_bt_cod_t cod = {.major = ESP_BT_COD_MAJOR_DEV_PERIPHERAL, .minor = ESP_BT_COD_MINOR_PERIPHERAL_COMBO};
    esp_bt_gap_set_cod(cod, ESP_BT_SET_COD_MAJOR_MINOR);
    esp_bt_io_cap_t io = ESP_BT_IO_CAP_NONE;
    esp_bt_gap_set_security_param(ESP_BT_SP_IOCAP_MODE, &io, sizeof io);
    esp_bt_hid_device_register_callback(hidd_cb);
    esp_bt_hid_device_init();
}

void hid_connect_last(void) {
    int n = esp_bt_gap_get_bond_device_num();
    if (n <= 0) return;
    esp_bd_addr_t list[4];
    if (n > 4) n = 4;
    esp_bt_gap_get_bond_device_list(&n, list);
    esp_bt_hid_device_connect(list[n - 1]);
}

void hid_discoverable(int seconds) {
    esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, seconds ? ESP_BT_GENERAL_DISCOVERABLE : ESP_BT_NON_DISCOVERABLE);
}

int hid_send(uint8_t id, const uint8_t *data, int len, bool skippable) {
    if (!bridge.phone_connected) return 2;
    if (skippable && in_lower > 0) {
        bridge.skipped++;
        return 1;
    }
    in_lower++;
    if (esp_bt_hid_device_send_report(ESP_HIDD_REPORT_TYPE_INTRDATA, id, len, (uint8_t *)data) != ESP_OK) {
        in_lower--;
        return 2;
    }
    bridge.reports++;
    bridge.pending = in_lower;
    return 0;
}
