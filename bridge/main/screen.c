// What the bridge's screen says, redrawn by one task (SPI never runs from the
// Bluetooth or Wi-Fi callbacks, which only ask for a redraw).
#include <stdio.h>
#include <string.h>

#include "bridge.h"
#include "settings.h"
#include "display.h"
#include "font_16.h"
#include "font_22.h"
#include "font_36.h"
#include "icons.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define BG RGB(0, 0, 0)
#define FG RGB(235, 235, 235)
#define DIM RGB(140, 140, 150)
#define GOOD RGB(80, 200, 120)
#define BAD RGB(240, 90, 80)
#define ACCENT RGB(175, 145, 255)  // the activity icon: the companion app's purple

static TaskHandle_t task;
static volatile uint32_t woke_ms;  // last input, state change or button press: the backlight stays up

#define DIM_AFTER_MS 120000  // on battery, the backlight dims this long after the last activity
#define DIM_PERCENT 15

static uint32_t now_ms(void) { return (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS); }

void screen_update(void) {
    if (task) xTaskNotifyGive(task);
}

void screen_wake(void) {
    woke_ms = now_ms();
    screen_update();
}

// Called for every input packet, so it only wakes the screen task when the icon would
// change: a new kind of input, or input after a quiet spell.
void bridge_activity(int kind) {
    uint32_t t = now_ms();
    bool change = kind != bridge.activity || t - bridge.activity_ms > ACT_SHOW_MS;
    bridge.activity = kind;
    bridge.activity_ms = t;
    woke_ms = t;
    if (change) screen_update();
}

// Rows remember what they show, and a row is sent to the panel only when its text or
// colour changes: the SPI transfer and the per-pixel blending are the screen's whole cost.
#define ROWS 8
static char shown_text[ROWS][48];
static uint16_t shown_fg[ROWS];

static void forget_rows(void) { memset(shown_text, 0, sizeof shown_text); }

static bool row(int i, int x, int y, const font_t *f, const char *text, uint16_t fg) {
    if (shown_fg[i] == fg && shown_text[i][0] && strncmp(shown_text[i], text, sizeof shown_text[i] - 1) == 0)
        return false;
    snprintf(shown_text[i], sizeof shown_text[i], "%s", text[0] ? text : " ");
    shown_fg[i] = fg;
    display_text(x, y, f, text, fg, BG);
    return true;
}

static const font_t *icon_for(int kind) {
    return kind == ACT_TAP ? &icon_tap : kind == ACT_KEYS ? &icon_keys : kind == ACT_POINTER ? &icon_pointer : NULL;
}

static void draw(void) {
    char a[48], b[48], c[48];
    int y = 6;
    switch (bridge.state) {
    case ST_SETUP:
        row(0, 8, y, &font22, "PhoneUse bridge", FG);
        y += font22.h + 10;
        row(1, 8, y, &font16, "Set it up from phoneuse:", DIM);
        y += font16.h + 2;
        row(2, 8, y, &font16, "Settings > Bluetooth bridge", FG);
        y += font16.h + 10;
        snprintf(a, sizeof a, "Bridge %.4s", bridge.id + 8);
        row(3, 8, y, &font16, a, DIM);
        break;
    case ST_CODE:
        row(0, 8, y, &font16, "Check that phoneuse shows", DIM);
        y += font16.h;
        row(1, 8, y, &font16, "the same code:", DIM);
        y += font16.h + 12;
        snprintf(a, sizeof a, "%03lu %03lu", (unsigned long)(bridge.code / 1000), (unsigned long)(bridge.code % 1000));
        row(2, -1, y, &font36, a, FG);
        break;
    case ST_JOINING:
        row(0, 8, y, &font22, "Joining Wi-Fi", FG);
        y += font22.h + 8;
        row(1, 8, y, &font16, settings.ssid, DIM);
        break;
    case ST_FAILED:
        row(0, 8, y, &font22, "Couldn't join", BAD);
        y += font22.h + 8;
        row(1, 8, y, &font16, settings.ssid, FG);
        y += font16.h + 2;
        row(2, 8, y, &font16, bridge.err, DIM);
        y += font16.h + 8;
        row(3, 8, y, &font16, "Try again in phoneuse", DIM);
        break;
    case ST_ONLINE: {
        // Fixed rows (135 px): network 4, phone 28 (with the activity icon at its right
        // end), two detail rows 62 and 84, radio and power 112.
        static uint32_t last_reports, last_at;
        static int icon_shown = -1;
        uint32_t t = now_ms();
        if (t - last_at >= 1000) {  // the rate row counts whole seconds, however often we draw
            snprintf(b, sizeof b, "%lu reports/s, %d waiting",
                     (unsigned long)((bridge.reports - last_reports) * 1000 / (t - last_at ? t - last_at : 1)),
                     bridge.pending);
            last_reports = bridge.reports, last_at = t;
        } else {
            snprintf(b, sizeof b, "%s", shown_text[2]);
        }
        snprintf(a, sizeof a, "%s  %s", settings.ssid, bridge.ip);
        row(0, 8, 4, &font16, a, DIM);
        bool name_drawn;
        if (bridge.phone_connected) {
            snprintf(a, sizeof a, "%.17s", bridge.phone[0] ? bridge.phone : "iPhone");  // room for the icon
            name_drawn = row(1, 8, 28, &font22, a, GOOD);
            uint32_t idle = t - bridge.last_cmd_ms;
            row(2, 8, 62, &font16, bridge.last_cmd_ms && idle < 5000 ? b : "Waiting for phoneuse", DIM);
            row(3, 8, 84, &font16, "", DIM);
        } else {
            name_drawn = row(1, 8, 28, &font22, "No phone", FG);
            row(2, 8, 62, &font16, "Pair on the iPhone:", DIM);
            row(3, 8, 84, &font16, "Bluetooth > " BRIDGE_NAME, FG);
        }
        int kind = bridge.phone_connected && t - bridge.activity_ms < ACT_SHOW_MS ? bridge.activity : ACT_NONE;
        const font_t *icon = icon_for(kind);
        if (name_drawn || kind != icon_shown) {
            int ix = DISPLAY_W - 8 - icon_pointer.w, iy = 28 + (font22.h - icon_pointer.h) / 2;
            if (icon) display_glyph(ix, iy, icon, 0, ACCENT, BG);
            else if (!name_drawn) display_glyph(ix, iy, &icon_pointer, 0, BG, BG);  // clear it
            icon_shown = kind;
        }
        int mv = bridge.battery_mv;
        if (mv > 4400) snprintf(c, sizeof c, "Wi-Fi %d dBm   USB power", bridge.wifi_rssi);  // no battery: the charger's output
        else if (mv > 0) snprintf(c, sizeof c, "Wi-Fi %d dBm   battery %.2f V", bridge.wifi_rssi, mv / 1000.0);
        else snprintf(c, sizeof c, "Wi-Fi %d dBm", bridge.wifi_rssi);
        row(4, 8, 112, &font16, c, DIM);
        break;
    }
    }
}

static void screen_task(void *arg) {
    int shown = -1, lit = 100;
    for (;;) {
        // a change, every 200 ms while the icon may need hiding, or once a second for the counters
        bool icon_up = now_ms() - bridge.activity_ms < ACT_SHOW_MS + 200;
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(icon_up ? 200 : 1000));
        int layout = bridge.state * 2 + bridge.phone_connected;  // rows differ between these
        if (layout != shown) {
            display_clear(BG);
            forget_rows();
            shown = layout;
            woke_ms = now_ms();
        }
        draw();
        bool battery = bridge.battery_mv > 0 && bridge.battery_mv <= 4400;
        int want = battery && now_ms() - woke_ms > DIM_AFTER_MS ? DIM_PERCENT : 100;
        if (want != lit) display_backlight(lit = want);
    }
}

void screen_start(void) {
    woke_ms = now_ms();
    xTaskCreatePinnedToCore(screen_task, "screen", 4096, NULL, 3, &task, 0);
}
