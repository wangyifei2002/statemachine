#include "app_fsm.h"
#include "app_format.h"
#include "app_fsm_config.h"
#include "app_health_monitor.h"
#include "stm32h7xx_hal.h"

#include <stdarg.h>
#include <string.h>

#define EVENT_BIT(event) (1UL << (uint32_t)(event))

typedef char event_flags_must_fit_u32[(EVT_COUNT <= 32) ? 1 : -1];

static fsm_state_t g_state;
static volatile uint32_t g_event_flags;
static uint32_t g_slot_count;
static uint32_t g_last_slot_tick;
static uint32_t g_state_enter_tick;
static uint32_t g_fault_module_mask;
static app_log_line_fn_t g_log_fn;
static fsm_state_t g_previous_state;
static app_event_t g_last_transition_cause;
static uint32_t g_last_transition_tick;

static uint32_t g_self_ok_count;
static uint32_t g_mm_valid_count;
static uint32_t g_gimbal_ready_count;
static uint32_t g_track_bad_count;
static uint32_t g_fallback_recover_count;
static uint32_t g_reacquire_lock_count;

static uint32_t g_last_bbu_seq;
static uint32_t g_last_gimbal_seq;
static uint32_t g_last_thz_seq;

static uint8_t g_fallback_wait_qbad_clear;
static uint32_t g_reacquire_last_cmd_tick;
static uint32_t g_reacquire_cmd_count;
static int16_t g_last_lock_az_deg;
static int16_t g_last_lock_el_deg;

static uint32_t g_recovery_attempt;
static uint32_t g_recovery_attempt_start_tick;
static uint32_t g_recovery_last_query_tick;
static uint32_t g_recovery_window_start_tick;
static uint32_t g_recovery_entry_count;
static app_fsm_actions_t g_actions;

static void fsm_log(const char *format, ...)
{
    char buffer[192];
    va_list args;

    if (g_log_fn == 0)
    {
        return;
    }

    va_start(args, format);
    App_FormatV(buffer, sizeof(buffer), format, args);
    va_end(args);
    g_log_fn(buffer);
}

static int32_t abs_i32(int32_t value)
{
    return (value < 0) ? -value : value;
}

static int32_t azimuth_delta_deg(int16_t first, int16_t second)
{
    int32_t delta;

    delta = (int32_t)first - (int32_t)second;
    if (delta > 180)
    {
        delta -= 360;
    }
    else if (delta < -180)
    {
        delta += 360;
    }
    return abs_i32(delta);
}

static uint8_t action_set_gimbal_target(int16_t az_deg, int16_t el_deg)
{
    if (g_actions.set_gimbal_target == 0)
    {
        return 1U;
    }
    return g_actions.set_gimbal_target(az_deg, el_deg);
}

static uint8_t action_send_thz_reacquire(void)
{
    if (g_actions.send_thz_reacquire == 0)
    {
        return 1U;
    }
    return g_actions.send_thz_reacquire();
}

static void action_for_fault_modules(uint8_t recover, uint32_t attempt)
{
    uint32_t i;

    for (i = 0U; i < APP_MODULE_COUNT; i++)
    {
        if ((g_fault_module_mask & (1UL << i)) == 0U)
        {
            continue;
        }
        if (recover)
        {
            if (g_actions.recover_module != 0)
            {
                (void)g_actions.recover_module((app_module_t)i, attempt);
            }
        }
        else if (g_actions.query_module != 0)
        {
            (void)g_actions.query_module((app_module_t)i);
        }
    }
}

static void reset_state_counters(void)
{
    g_self_ok_count = 0U;
    g_mm_valid_count = 0U;
    g_gimbal_ready_count = 0U;
    g_track_bad_count = 0U;
    g_fallback_recover_count = 0U;
    g_reacquire_lock_count = 0U;
}

static void sync_input_sequences(void)
{
    const app_device_snapshot_t *input = App_HealthMonitor_GetSnapshot();

    g_last_bbu_seq = input->bbu_data_seq;
    g_last_gimbal_seq = input->gimbal_status_seq;
    g_last_thz_seq = input->thz_status_seq;
}

static void clear_state_local_events(void)
{
    uint32_t mask;
    uint32_t primask;

    mask = EVENT_BIT(EVT_SELF_OK) |
           EVENT_BIT(EVT_SELF_FAIL) |
           EVENT_BIT(EVT_MM_OK) |
           EVENT_BIT(EVT_GIMBAL_OK) |
           EVENT_BIT(EVT_THZ_LOCK) |
           EVENT_BIT(EVT_TIMEOUT) |
           EVENT_BIT(EVT_LOST) |
           EVENT_BIT(EVT_MM_RECOVER) |
           EVENT_BIT(EVT_NO_RECOVER) |
           EVENT_BIT(EVT_REACQUIRE_OK) |
           EVENT_BIT(EVT_REACQUIRE_TIMEOUT) |
           EVENT_BIT(EVT_REACQUIRE_REALIGN) |
           EVENT_BIT(EVT_RECOVERY_OK) |
           EVENT_BIT(EVT_RECOVERY_TIMEOUT) |
           EVENT_BIT(EVT_TARGET_LOST) |
           EVENT_BIT(EVT_GIMBAL_ALIGN_TIMEOUT);

    primask = __get_PRIMASK();
    __disable_irq();
    g_event_flags &= ~mask;
    if (!primask)
    {
        __enable_irq();
    }
}

static void send_reacquire_command(uint32_t now)
{
    g_reacquire_cmd_count++;
    g_reacquire_last_cmd_tick = now;
    fsm_log("[slot=%lu] ACTION: THZ reacquire command %lu/%u",
            (unsigned long)g_slot_count,
            (unsigned long)g_reacquire_cmd_count,
            REACQUIRE_CMD_MAX_SENDS);
    if (!action_send_thz_reacquire())
    {
        fsm_log("ACTION failed: THZ reacquire command not accepted");
    }
}

static void fsm_transition(fsm_state_t new_state,
                           app_event_t cause,
                           uint32_t now)
{
    const app_device_snapshot_t *input;
    fsm_state_t old_state;

    old_state = g_state;
    if (old_state == new_state)
    {
        return;
    }

    clear_state_local_events();
    g_previous_state = old_state;
    g_last_transition_cause = cause;
    g_last_transition_tick = now;
    g_state = new_state;
    g_state_enter_tick = now;
    reset_state_counters();
    sync_input_sequences();
    g_fallback_wait_qbad_clear = 0U;

    fsm_log("[slot=%lu] STATE %s -> %s, cause=%s",
            (unsigned long)g_slot_count,
            App_Fsm_StateToString(old_state),
            App_Fsm_StateToString(new_state),
            App_Fsm_EventToString(cause));

    input = App_HealthMonitor_GetSnapshot();

    switch (new_state)
    {
    case S_FAULT:
        if (g_actions.stop_active_operations != 0)
        {
            g_actions.stop_active_operations();
        }
        break;

    case S2_COARSE_ALIGN:
        if (!action_set_gimbal_target(input->target_az_deg,
                                      input->target_el_deg))
        {
            fsm_log("ACTION failed: gimbal target command not accepted");
        }
        break;

    case S5_FALLBACK:
        g_fallback_wait_qbad_clear =
            (uint8_t)((cause == EVT_REACQUIRE_TIMEOUT) ||
                      (cause == EVT_LOST));
        fsm_log("S5 entry: invalidate pre-entry samples and start full fallback");
        break;

    case S6_REACQUIRE:
        g_reacquire_cmd_count = 0U;
        fsm_log("S6 entry: preserve BBU/gimbal, invalidate THZ lock");
        fsm_log("ACTION: read BBU target and correct gimbal");
        (void)action_set_gimbal_target(input->target_az_deg,
                                       input->target_el_deg);
        send_reacquire_command(now);
        break;

    case S7_MODULE_RECOVERY:
        if ((now - g_recovery_window_start_tick) >
            RECOVERY_REENTRY_WINDOW_MS)
        {
            g_recovery_window_start_tick = now;
            g_recovery_entry_count = 0U;
        }
        g_recovery_entry_count++;
        g_recovery_attempt = 1U;
        g_recovery_attempt_start_tick = now;
        g_recovery_last_query_tick = now;
        if (g_actions.stop_active_operations != 0)
        {
            g_actions.stop_active_operations();
        }
        action_for_fault_modules(1U, g_recovery_attempt);
        fsm_log("S7 entry: stop pointing/capture actions, fault_mask=0x%02lX",
                (unsigned long)g_fault_module_mask);
        if (g_recovery_entry_count >= RECOVERY_REENTRY_MAX)
        {
            fsm_log("S7 unstable: entered %u times within %lu ms",
                    RECOVERY_REENTRY_MAX,
                    (unsigned long)RECOVERY_REENTRY_WINDOW_MS);
            App_Fsm_PostEvent(EVT_RECOVERY_TIMEOUT);
        }
        break;

    case S4_TRACK:
        g_last_lock_az_deg = input->target_az_deg;
        g_last_lock_el_deg = input->target_el_deg;
        break;

    default:
        break;
    }
}

static void enter_fault(const char *reason, uint32_t now)
{
    fsm_log("FAULT: %s", reason);
    fsm_transition(S_FAULT, EVT_FAULT, now);
}

static uint8_t consume_event(app_event_t event)
{
    uint8_t present;
    uint32_t primask;

    if ((event <= EVT_NONE) || (event >= EVT_COUNT) ||
        ((uint32_t)event >= 32U))
    {
        return 0U;
    }

    primask = __get_PRIMASK();
    __disable_irq();
    present = (g_event_flags & EVENT_BIT(event)) ? 1U : 0U;
    g_event_flags &= ~EVENT_BIT(event);
    if (!primask)
    {
        __enable_irq();
    }
    return present;
}

static uint32_t collect_module_fault_events(app_event_t *first_cause)
{
    uint32_t mask = 0U;

    if (consume_event(EVT_BBU_OFFLINE))
    {
        mask |= APP_MODULE_MASK_BBU;
        *first_cause = EVT_BBU_OFFLINE;
    }
    if (consume_event(EVT_BBU_NOT_READY))
    {
        mask |= APP_MODULE_MASK_BBU;
        if (*first_cause == EVT_NONE)
        {
            *first_cause = EVT_BBU_NOT_READY;
        }
    }
    if (consume_event(EVT_BBU_DATA_STALE))
    {
        mask |= APP_MODULE_MASK_BBU;
        if (*first_cause == EVT_NONE)
        {
            *first_cause = EVT_BBU_DATA_STALE;
        }
    }
    if (consume_event(EVT_THZ_OFFLINE))
    {
        mask |= APP_MODULE_MASK_THZ;
        if (*first_cause == EVT_NONE)
        {
            *first_cause = EVT_THZ_OFFLINE;
        }
    }
    if (consume_event(EVT_THZ_NOT_READY))
    {
        mask |= APP_MODULE_MASK_THZ;
        if (*first_cause == EVT_NONE)
        {
            *first_cause = EVT_THZ_NOT_READY;
        }
    }
    if (consume_event(EVT_GIMBAL_OFFLINE))
    {
        mask |= APP_MODULE_MASK_GIMBAL;
        if (*first_cause == EVT_NONE)
        {
            *first_cause = EVT_GIMBAL_OFFLINE;
        }
    }
    if (consume_event(EVT_GIMBAL_NOT_READY))
    {
        mask |= APP_MODULE_MASK_GIMBAL;
        if (*first_cause == EVT_NONE)
        {
            *first_cause = EVT_GIMBAL_NOT_READY;
        }
    }
    if (consume_event(EVT_GIMBAL_ERROR))
    {
        mask |= APP_MODULE_MASK_GIMBAL;
        if (*first_cause == EVT_NONE)
        {
            *first_cause = EVT_GIMBAL_ERROR;
        }
    }
    return mask;
}

static void consume_recovered_notifications(void)
{
    if (consume_event(EVT_BBU_RECOVERED))
    {
        fsm_log("HEALTH: BBU communication/data recovered");
    }
    if (consume_event(EVT_THZ_RECOVERED))
    {
        fsm_log("HEALTH: THZ module recovered");
    }
    if (consume_event(EVT_GIMBAL_RECOVERED))
    {
        fsm_log("HEALTH: gimbal recovered");
    }
}

static void run_self_check(const app_device_snapshot_t *input,
                           uint32_t now)
{
    if (input->bbu_online && input->bbu_ready &&
        input->thz_online && input->thz_ready &&
        input->gimbal_online && input->gimbal_module_ready)
    {
        g_self_ok_count++;
        fsm_log("[slot=%lu] S0 self check: %lu/%u",
                (unsigned long)g_slot_count,
                (unsigned long)g_self_ok_count,
                SELF_CHECK_PASS_SLOTS);
        if (g_self_ok_count >= SELF_CHECK_PASS_SLOTS)
        {
            App_Fsm_PostEvent(EVT_SELF_OK);
        }
    }
    else
    {
        g_self_ok_count = 0U;
    }

    if ((now - g_state_enter_tick) >= SELF_CHECK_TIMEOUT_MS)
    {
        App_Fsm_PostEvent(EVT_SELF_FAIL);
    }
}

static void run_search(const app_device_snapshot_t *input)
{
    if (input->bbu_data_seq == g_last_bbu_seq)
    {
        return;
    }
    g_last_bbu_seq = input->bbu_data_seq;

    if (input->bbu_online && input->bbu_ready &&
        input->bbu_data_fresh && input->mm_target_valid)
    {
        g_mm_valid_count++;
        fsm_log("[slot=%lu] S1 target stable: %lu/%u",
                (unsigned long)g_slot_count,
                (unsigned long)g_mm_valid_count,
                MM_STABLE_SLOTS);
        if (g_mm_valid_count >= MM_STABLE_SLOTS)
        {
            App_Fsm_PostEvent(EVT_MM_OK);
        }
    }
    else
    {
        g_mm_valid_count = 0U;
    }
}

static void run_coarse_align(const app_device_snapshot_t *input,
                             uint32_t now)
{
    if ((!input->bbu_data_fresh) || (!input->mm_target_valid))
    {
        App_Fsm_PostEvent(EVT_TARGET_LOST);
        return;
    }

    if ((now - g_state_enter_tick) >= COARSE_ALIGN_TIMEOUT_MS)
    {
        App_Fsm_PostEvent(EVT_GIMBAL_ALIGN_TIMEOUT);
        return;
    }

    if (input->gimbal_status_seq == g_last_gimbal_seq)
    {
        return;
    }
    g_last_gimbal_seq = input->gimbal_status_seq;

    if (input->gimbal_online && input->gimbal_module_ready &&
        (!input->gimbal_error) && input->gimbal_ready)
    {
        g_gimbal_ready_count++;
        fsm_log("[slot=%lu] S2 gimbal ready: %lu/%u",
                (unsigned long)g_slot_count,
                (unsigned long)g_gimbal_ready_count,
                GIMBAL_READY_SLOTS);
        if (g_gimbal_ready_count >= GIMBAL_READY_SLOTS)
        {
            App_Fsm_PostEvent(EVT_GIMBAL_OK);
        }
    }
    else
    {
        g_gimbal_ready_count = 0U;
    }
}

static void run_capture(const app_device_snapshot_t *input, uint32_t now)
{
    if ((!input->bbu_data_fresh) || (!input->mm_target_valid))
    {
        App_Fsm_PostEvent(EVT_TARGET_LOST);
        return;
    }

    if (input->thz_status_seq != g_last_thz_seq)
    {
        g_last_thz_seq = input->thz_status_seq;
        if (input->thz_online && input->thz_ready &&
            input->thz_locked && (!input->thz_quality_bad))
        {
            App_Fsm_PostEvent(EVT_THZ_LOCK);
            return;
        }
    }

    if ((now - g_state_enter_tick) >= CAPTURE_TIMEOUT_MS)
    {
        App_Fsm_PostEvent(EVT_TIMEOUT);
    }
}

static void run_track(const app_device_snapshot_t *input)
{
    int32_t az_delta;
    int32_t el_delta;

    if (input->bbu_data_seq != g_last_bbu_seq)
    {
        g_last_bbu_seq = input->bbu_data_seq;
        if ((!input->bbu_data_fresh) || (!input->mm_target_valid))
        {
            App_Fsm_PostEvent(EVT_TARGET_LOST);
            return;
        }

        az_delta = azimuth_delta_deg(input->target_az_deg,
                                     g_last_lock_az_deg);
        el_delta = abs_i32((int32_t)input->target_el_deg -
                           (int32_t)g_last_lock_el_deg);
        if ((az_delta > TRACK_REALIGN_AZ_DELTA_DEG) ||
            (el_delta > TRACK_REALIGN_EL_DELTA_DEG))
        {
            fsm_log("S4 target moved: d_az=%ld deg d_el=%ld deg",
                    (long)az_delta, (long)el_delta);
            App_Fsm_PostEvent(EVT_REACQUIRE_REALIGN);
            return;
        }

        if ((az_delta != 0) || (el_delta != 0))
        {
            if (action_set_gimbal_target(input->target_az_deg,
                                         input->target_el_deg))
            {
                g_last_lock_az_deg = input->target_az_deg;
                g_last_lock_el_deg = input->target_el_deg;
            }
            else
            {
                fsm_log("ACTION failed: S4 gimbal correction not accepted");
            }
        }
    }

    if (input->thz_status_seq == g_last_thz_seq)
    {
        return;
    }
    g_last_thz_seq = input->thz_status_seq;

    if (input->thz_quality_bad || (!input->thz_locked))
    {
        g_track_bad_count++;
        fsm_log("[slot=%lu] S4 bad quality: %lu/%u",
                (unsigned long)g_slot_count,
                (unsigned long)g_track_bad_count,
                TRACK_BAD_SLOTS);
        if (g_track_bad_count >= TRACK_BAD_SLOTS)
        {
            App_Fsm_PostEvent(EVT_LOST);
        }
    }
    else
    {
        g_track_bad_count = 0U;
    }
}

static void run_fallback(const app_device_snapshot_t *input, uint32_t now)
{
    if (g_fallback_wait_qbad_clear)
    {
        if ((!input->thz_quality_bad) ||
            ((now - g_state_enter_tick) >=
             FALLBACK_QBAD_CLEAR_TIMEOUT_MS))
        {
            if (input->thz_quality_bad)
            {
                fsm_log("S5 qbad clear wait timed out; continue fallback");
            }
            else
            {
                fsm_log("S5 qbad cleared; continue fallback");
            }
            g_fallback_wait_qbad_clear = 0U;
            g_state_enter_tick = now;
            g_fallback_recover_count = 0U;
            g_last_bbu_seq = input->bbu_data_seq;
        }
        return;
    }

    if (input->bbu_data_seq != g_last_bbu_seq)
    {
        g_last_bbu_seq = input->bbu_data_seq;
        if (input->bbu_online && input->bbu_ready &&
            input->bbu_data_fresh && input->mm_target_valid)
        {
            g_fallback_recover_count++;
            fsm_log("[slot=%lu] S5 target recovery: %lu/%u",
                    (unsigned long)g_slot_count,
                    (unsigned long)g_fallback_recover_count,
                    FALLBACK_RECOVER_STABLE_SLOTS);
            if (g_fallback_recover_count >=
                FALLBACK_RECOVER_STABLE_SLOTS)
            {
                App_Fsm_PostEvent(EVT_MM_RECOVER);
                return;
            }
        }
        else
        {
            g_fallback_recover_count = 0U;
        }
    }

    if ((now - g_state_enter_tick) >=
        FALLBACK_NO_RECOVER_TIMEOUT_MS)
    {
        App_Fsm_PostEvent(EVT_NO_RECOVER);
    }
}

static void run_reacquire(const app_device_snapshot_t *input,
                          uint32_t now)
{
    int32_t az_delta;
    int32_t el_delta;

    if ((!input->bbu_online) || (!input->bbu_ready) ||
        (!input->bbu_data_fresh) || (!input->mm_target_valid))
    {
        fsm_log("S6 prerequisite lost: no fresh BBU target");
        App_Fsm_PostEvent(EVT_TARGET_LOST);
        return;
    }

    az_delta = azimuth_delta_deg(input->target_az_deg,
                                 g_last_lock_az_deg);
    el_delta = abs_i32((int32_t)input->target_el_deg -
                       (int32_t)g_last_lock_el_deg);
    if ((az_delta > REACQUIRE_MAX_AZ_DELTA_DEG) ||
        (el_delta > REACQUIRE_MAX_EL_DELTA_DEG))
    {
        fsm_log("S6 target moved: d_az=%ld deg d_el=%ld deg",
                (long)az_delta, (long)el_delta);
        App_Fsm_PostEvent(EVT_REACQUIRE_REALIGN);
        return;
    }

    if (input->thz_status_seq != g_last_thz_seq)
    {
        g_last_thz_seq = input->thz_status_seq;
        if (input->thz_locked && (!input->thz_quality_bad))
        {
            g_reacquire_lock_count++;
            fsm_log("[slot=%lu] S6 lock stable: %lu/%u",
                    (unsigned long)g_slot_count,
                    (unsigned long)g_reacquire_lock_count,
                    REACQUIRE_LOCK_STABLE_SLOTS);
            if (g_reacquire_lock_count >=
                REACQUIRE_LOCK_STABLE_SLOTS)
            {
                App_Fsm_PostEvent(EVT_REACQUIRE_OK);
                return;
            }
        }
        else
        {
            g_reacquire_lock_count = 0U;
        }
    }

    if ((g_reacquire_cmd_count < REACQUIRE_CMD_MAX_SENDS) &&
        ((now - g_reacquire_last_cmd_tick) >=
         REACQUIRE_CMD_INTERVAL_MS))
    {
        send_reacquire_command(now);
    }

    if ((now - g_state_enter_tick) >= REACQUIRE_TIMEOUT_MS)
    {
        App_Fsm_PostEvent(EVT_REACQUIRE_TIMEOUT);
    }
}

static void clear_recovered_fault_modules(const app_device_snapshot_t *input)
{
    if ((g_fault_module_mask & APP_MODULE_MASK_BBU) &&
        input->bbu_online && input->bbu_ready &&
        input->bbu_data_fresh &&
        ((g_actions.reapply_module_config == 0) ||
         g_actions.reapply_module_config(APP_MODULE_BBU)))
    {
        fsm_log("S7 BBU recovered; configuration reapplied");
        g_fault_module_mask &= ~APP_MODULE_MASK_BBU;
    }

    if ((g_fault_module_mask & APP_MODULE_MASK_GIMBAL) &&
        input->gimbal_online && input->gimbal_module_ready &&
        (!input->gimbal_error) &&
        ((g_actions.reapply_module_config == 0) ||
         g_actions.reapply_module_config(APP_MODULE_GIMBAL)))
    {
        fsm_log("S7 gimbal recovered; configuration reapplied");
        g_fault_module_mask &= ~APP_MODULE_MASK_GIMBAL;
    }

    if ((g_fault_module_mask & APP_MODULE_MASK_THZ) &&
        input->thz_online && input->thz_ready &&
        ((g_actions.reapply_module_config == 0) ||
         g_actions.reapply_module_config(APP_MODULE_THZ)))
    {
        fsm_log("S7 THZ recovered; configuration reapplied");
        g_fault_module_mask &= ~APP_MODULE_MASK_THZ;
    }
}

static void run_module_recovery(const app_device_snapshot_t *input,
                                uint32_t now)
{
    clear_recovered_fault_modules(input);

    if (g_fault_module_mask == 0U)
    {
        App_Fsm_PostEvent(EVT_RECOVERY_OK);
        return;
    }

    if ((now - g_recovery_last_query_tick) >=
        RECOVERY_QUERY_PERIOD_MS)
    {
        g_recovery_last_query_tick = now;
        fsm_log("[slot=%lu] S7 query modules, mask=0x%02lX attempt=%lu/%u",
                (unsigned long)g_slot_count,
                (unsigned long)g_fault_module_mask,
                (unsigned long)g_recovery_attempt,
                RECOVERY_MAX_ATTEMPTS);
        action_for_fault_modules(0U, g_recovery_attempt);
    }

    if ((now - g_recovery_attempt_start_tick) >=
        RECOVERY_TIMEOUT_MS)
    {
        if (g_recovery_attempt >= RECOVERY_MAX_ATTEMPTS)
        {
            App_Fsm_PostEvent(EVT_RECOVERY_TIMEOUT);
        }
        else
        {
            g_recovery_attempt++;
            g_recovery_attempt_start_tick = now;
            action_for_fault_modules(1U, g_recovery_attempt);
            fsm_log("S7 start recovery attempt %lu/%u",
                    (unsigned long)g_recovery_attempt,
                    RECOVERY_MAX_ATTEMPTS);
        }
    }
}

static void run_slot_once(uint32_t now)
{
    const app_device_snapshot_t *input;

    g_slot_count++;
    input = App_HealthMonitor_GetSnapshot();

    switch (g_state)
    {
    case S_IDLE:
    case S_FAULT:
        break;
    case S0_SELF_CHECK:
        run_self_check(input, now);
        break;
    case S1_SEARCH:
        run_search(input);
        break;
    case S2_COARSE_ALIGN:
        run_coarse_align(input, now);
        break;
    case S3_CAPTURE:
        run_capture(input, now);
        break;
    case S4_TRACK:
        run_track(input);
        break;
    case S5_FALLBACK:
        run_fallback(input, now);
        break;
    case S6_REACQUIRE:
        run_reacquire(input, now);
        break;
    case S7_MODULE_RECOVERY:
        run_module_recovery(input, now);
        break;
    default:
        App_Fsm_PostEvent(EVT_FAULT);
        break;
    }
}

void App_Fsm_Init(uint32_t now, app_log_line_fn_t log_fn)
{
    g_log_fn = log_fn;
    memset(&g_actions, 0, sizeof(g_actions));
    g_recovery_window_start_tick = now;
    g_recovery_entry_count = 0U;
    App_Fsm_Reset(now, 0U);
}

void App_Fsm_SetActions(const app_fsm_actions_t *actions)
{
    if (actions == 0)
    {
        memset(&g_actions, 0, sizeof(g_actions));
    }
    else
    {
        g_actions = *actions;
    }
}

void App_Fsm_Reset(uint32_t now, uint8_t clear_simulated_inputs)
{
    uint32_t primask;

    if (g_actions.stop_active_operations != 0)
    {
        g_actions.stop_active_operations();
    }

    if (clear_simulated_inputs)
    {
        App_HealthMonitor_ResetSimulation(now);
    }

    primask = __get_PRIMASK();
    __disable_irq();
    g_event_flags = 0U;
    if (!primask)
    {
        __enable_irq();
    }

    g_state = S_IDLE;
    g_previous_state = S_IDLE;
    g_last_transition_cause = EVT_RESET;
    g_last_transition_tick = now;
    g_slot_count = 0U;
    g_last_slot_tick = now;
    g_state_enter_tick = now;
    g_fault_module_mask = 0U;
    g_fallback_wait_qbad_clear = 0U;
    g_reacquire_cmd_count = 0U;
    g_recovery_attempt = 0U;
    g_recovery_window_start_tick = now;
    g_recovery_entry_count = 0U;
    g_last_lock_az_deg = 0;
    g_last_lock_el_deg = 0;
    reset_state_counters();
    sync_input_sequences();
    fsm_log("[slot=0] STATE -> S_IDLE, reset complete");
}

void App_Fsm_Run(uint32_t now)
{
    if ((now - g_last_slot_tick) >= SLOT_PERIOD_MS)
    {
        g_last_slot_tick = now;
        run_slot_once(now);
    }
}

void App_Fsm_PostEvent(app_event_t event)
{
    uint32_t primask;
    uint8_t added = 0U;

    if ((event <= EVT_NONE) || (event >= EVT_COUNT) ||
        ((uint32_t)event >= 32U))
    {
        return;
    }

    primask = __get_PRIMASK();
    __disable_irq();
    if ((g_event_flags & EVENT_BIT(event)) == 0U)
    {
        g_event_flags |= EVENT_BIT(event);
        added = 1U;
    }
    if (!primask)
    {
        __enable_irq();
    }

    if (added)
    {
        fsm_log("[slot=%lu] EVENT + %s",
                (unsigned long)g_slot_count,
                App_Fsm_EventToString(event));
    }
}

void App_Fsm_PostHealthEvent(app_event_t event)
{
    if (App_Fsm_IsRuntimeState())
    {
        App_Fsm_PostEvent(event);
    }
}

void App_Fsm_ProcessEvents(uint32_t now)
{
    const app_device_snapshot_t *input;
    uint32_t new_faults;
    app_event_t fault_cause;

    if (consume_event(EVT_RESET))
    {
        App_Fsm_Reset(now, 0U);
        return;
    }

    if (consume_event(EVT_FAULT))
    {
        enter_fault("manual or illegal-state fault", now);
        return;
    }

    fault_cause = EVT_NONE;
    new_faults = collect_module_fault_events(&fault_cause);
    if (new_faults != 0U)
    {
        g_fault_module_mask |= new_faults;
        fsm_log("HEALTH fault mask updated: 0x%02lX",
                (unsigned long)g_fault_module_mask);
        if ((g_state >= S1_SEARCH) &&
            (g_state <= S6_REACQUIRE))
        {
            fsm_transition(S7_MODULE_RECOVERY,
                           fault_cause,
                           now);
            return;
        }
    }

    consume_recovered_notifications();

    switch (g_state)
    {
    case S_IDLE:
        if (consume_event(EVT_START))
        {
            fsm_transition(S0_SELF_CHECK, EVT_START, now);
        }
        break;

    case S_FAULT:
        break;

    case S0_SELF_CHECK:
        if (consume_event(EVT_SELF_FAIL))
        {
            enter_fault("self check timed out or failed", now);
        }
        else if (consume_event(EVT_SELF_OK))
        {
            fsm_transition(S1_SEARCH, EVT_SELF_OK, now);
        }
        break;

    case S1_SEARCH:
        if (consume_event(EVT_MM_OK))
        {
            fsm_transition(S2_COARSE_ALIGN, EVT_MM_OK, now);
        }
        break;

    case S2_COARSE_ALIGN:
        if (consume_event(EVT_TARGET_LOST))
        {
            fsm_transition(S1_SEARCH, EVT_TARGET_LOST, now);
        }
        else if (consume_event(EVT_GIMBAL_ALIGN_TIMEOUT))
        {
            enter_fault("gimbal coarse alignment timed out", now);
        }
        else if (consume_event(EVT_GIMBAL_OK))
        {
            fsm_transition(S3_CAPTURE, EVT_GIMBAL_OK, now);
        }
        break;

    case S3_CAPTURE:
        if (consume_event(EVT_TARGET_LOST))
        {
            fsm_transition(S5_FALLBACK, EVT_TARGET_LOST, now);
        }
        else if (consume_event(EVT_THZ_LOCK))
        {
            fsm_transition(S4_TRACK, EVT_THZ_LOCK, now);
        }
        else if (consume_event(EVT_TIMEOUT))
        {
            fsm_transition(S5_FALLBACK, EVT_TIMEOUT, now);
        }
        break;

    case S4_TRACK:
        if (consume_event(EVT_TARGET_LOST))
        {
            fsm_transition(S5_FALLBACK, EVT_TARGET_LOST, now);
        }
        else if (consume_event(EVT_REACQUIRE_REALIGN))
        {
            fsm_transition(S2_COARSE_ALIGN,
                           EVT_REACQUIRE_REALIGN,
                           now);
        }
        else if (consume_event(EVT_LOST))
        {
            fsm_transition(S6_REACQUIRE, EVT_LOST, now);
        }
        break;

    case S5_FALLBACK:
        if (consume_event(EVT_MM_RECOVER))
        {
            fsm_transition(S2_COARSE_ALIGN, EVT_MM_RECOVER, now);
        }
        else if (consume_event(EVT_NO_RECOVER))
        {
            fsm_transition(S1_SEARCH, EVT_NO_RECOVER, now);
        }
        break;

    case S6_REACQUIRE:
        if (consume_event(EVT_TARGET_LOST))
        {
            fsm_transition(S5_FALLBACK, EVT_TARGET_LOST, now);
        }
        else if (consume_event(EVT_REACQUIRE_REALIGN))
        {
            fsm_transition(S2_COARSE_ALIGN,
                           EVT_REACQUIRE_REALIGN,
                           now);
        }
        else if (consume_event(EVT_REACQUIRE_OK))
        {
            fsm_transition(S4_TRACK, EVT_REACQUIRE_OK, now);
        }
        else if (consume_event(EVT_REACQUIRE_TIMEOUT))
        {
            fsm_transition(S5_FALLBACK,
                           EVT_REACQUIRE_TIMEOUT,
                           now);
        }
        break;

    case S7_MODULE_RECOVERY:
        if (consume_event(EVT_RECOVERY_OK))
        {
            input = App_HealthMonitor_GetSnapshot();
            if (input->bbu_data_fresh && input->mm_target_valid)
            {
                fsm_transition(S2_COARSE_ALIGN,
                               EVT_RECOVERY_OK,
                               now);
            }
            else
            {
                fsm_transition(S1_SEARCH, EVT_RECOVERY_OK, now);
            }
        }
        else if (consume_event(EVT_RECOVERY_TIMEOUT))
        {
            enter_fault("module recovery failed", now);
        }
        break;

    default:
        enter_fault("illegal state", now);
        break;
    }
}

fsm_state_t App_Fsm_GetState(void)
{
    return g_state;
}

uint32_t App_Fsm_GetSlotCount(void)
{
    return g_slot_count;
}

uint32_t App_Fsm_GetEventFlags(void)
{
    return g_event_flags;
}

uint32_t App_Fsm_GetFaultModuleMask(void)
{
    return g_fault_module_mask;
}

uint8_t App_Fsm_IsRuntimeState(void)
{
    return (uint8_t)((g_state >= S1_SEARCH) &&
                     (g_state <= S7_MODULE_RECOVERY));
}

const char *App_Fsm_StateToString(fsm_state_t state)
{
    switch (state)
    {
    case S_IDLE:              return "S_IDLE";
    case S_FAULT:             return "S_FAULT";
    case S0_SELF_CHECK:       return "S0_SELF_CHECK";
    case S1_SEARCH:           return "S1_SEARCH";
    case S2_COARSE_ALIGN:     return "S2_COARSE_ALIGN";
    case S3_CAPTURE:          return "S3_CAPTURE";
    case S4_TRACK:            return "S4_TRACK";
    case S5_FALLBACK:         return "S5_FALLBACK";
    case S6_REACQUIRE:        return "S6_REACQUIRE";
    case S7_MODULE_RECOVERY:  return "S7_MODULE_RECOVERY";
    default:                  return "UNKNOWN";
    }
}

const char *App_Fsm_EventToString(app_event_t event)
{
    switch (event)
    {
    case EVT_START:                 return "EVT_START";
    case EVT_RESET:                 return "EVT_RESET";
    case EVT_FAULT:                 return "EVT_FAULT";
    case EVT_SELF_OK:               return "EVT_SELF_OK";
    case EVT_SELF_FAIL:             return "EVT_SELF_FAIL";
    case EVT_MM_OK:                 return "EVT_MM_OK";
    case EVT_GIMBAL_OK:             return "EVT_GIMBAL_OK";
    case EVT_THZ_LOCK:              return "EVT_THZ_LOCK";
    case EVT_TIMEOUT:               return "EVT_TIMEOUT";
    case EVT_LOST:                  return "EVT_LOST";
    case EVT_MM_RECOVER:            return "EVT_MM_RECOVER";
    case EVT_NO_RECOVER:            return "EVT_NO_RECOVER";
    case EVT_BBU_OFFLINE:           return "EVT_BBU_OFFLINE";
    case EVT_BBU_NOT_READY:         return "EVT_BBU_NOT_READY";
    case EVT_BBU_RECOVERED:         return "EVT_BBU_RECOVERED";
    case EVT_BBU_DATA_STALE:        return "EVT_BBU_DATA_STALE";
    case EVT_THZ_OFFLINE:           return "EVT_THZ_OFFLINE";
    case EVT_THZ_NOT_READY:         return "EVT_THZ_NOT_READY";
    case EVT_THZ_RECOVERED:         return "EVT_THZ_RECOVERED";
    case EVT_GIMBAL_OFFLINE:        return "EVT_GIMBAL_OFFLINE";
    case EVT_GIMBAL_NOT_READY:      return "EVT_GIMBAL_NOT_READY";
    case EVT_GIMBAL_RECOVERED:      return "EVT_GIMBAL_RECOVERED";
    case EVT_GIMBAL_ERROR:          return "EVT_GIMBAL_ERROR";
    case EVT_REACQUIRE_OK:          return "EVT_REACQUIRE_OK";
    case EVT_REACQUIRE_TIMEOUT:     return "EVT_REACQUIRE_TIMEOUT";
    case EVT_REACQUIRE_REALIGN:     return "EVT_REACQUIRE_REALIGN";
    case EVT_RECOVERY_OK:           return "EVT_RECOVERY_OK";
    case EVT_RECOVERY_TIMEOUT:      return "EVT_RECOVERY_TIMEOUT";
    case EVT_TARGET_LOST:           return "EVT_TARGET_LOST";
    case EVT_GIMBAL_ALIGN_TIMEOUT:  return "EVT_GIMBAL_ALIGN_TIMEOUT";
    default:                        return "EVT_NONE";
    }
}

void App_Fsm_PrintStatus(void)
{
    const app_device_snapshot_t *input;

    input = App_HealthMonitor_GetSnapshot();
    fsm_log("STATE=%s prev=%s cause=%s state_ms=%lu",
            App_Fsm_StateToString(g_state),
            App_Fsm_StateToString(g_previous_state),
            App_Fsm_EventToString(g_last_transition_cause),
            (unsigned long)(HAL_GetTick() - g_last_transition_tick));
    fsm_log("slot=%lu events=0x%08lX fault_mask=0x%02lX recovery=%lu/%u",
            (unsigned long)g_slot_count,
            (unsigned long)g_event_flags,
            (unsigned long)g_fault_module_mask,
            (unsigned long)g_recovery_attempt,
            RECOVERY_MAX_ATTEMPTS);
    fsm_log("HEALTH: BBU=%u/%u/fresh=%u THZ=%u/%u GIMBAL=%u/%u/error=%u",
            (unsigned int)input->bbu_online,
            (unsigned int)input->bbu_ready,
            (unsigned int)input->bbu_data_fresh,
            (unsigned int)input->thz_online,
            (unsigned int)input->thz_ready,
            (unsigned int)input->gimbal_online,
            (unsigned int)input->gimbal_module_ready,
            (unsigned int)input->gimbal_error);
    fsm_log("INPUT: target=%u angle=(%d,%d) gimbal_ready=%u thz_lock=%u qbad=%u",
            (unsigned int)input->mm_target_valid,
            input->target_az_deg,
            input->target_el_deg,
            (unsigned int)input->gimbal_ready,
            (unsigned int)input->thz_locked,
            (unsigned int)input->thz_quality_bad);
}
