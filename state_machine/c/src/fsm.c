#include "fsm.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

static uint8_t sample_fresh(const fsm_sample_meta_t *meta, uint16_t max_age)
{
    return (uint8_t)((meta->valid != 0U) && (meta->age_slots <= max_age));
}

static int32_t abs_i32(int32_t value)
{
    return (value < 0) ? -value : value;
}

static void clear_counters(fsm_context_t *ctx)
{
    memset(ctx->counters, 0, sizeof(ctx->counters));
}

static uint16_t count_condition(fsm_context_t *ctx, fsm_counter_t counter, uint8_t condition)
{
    if (condition != 0U) {
        if (ctx->counters[counter] < UINT16_MAX) {
            ctx->counters[counter]++;
        }
    } else {
        ctx->counters[counter] = 0U;
    }
    return ctx->counters[counter];
}

static void transition(fsm_context_t *ctx, fsm_state_t state, uint32_t slot_id)
{
    ctx->state = state;
    ctx->state_enter_slot = slot_id;
    clear_counters(ctx);
}

static uint32_t health_fault_mask(const fsm_input_t *input)
{
    uint32_t mask = input->explicit_fault_mask;
    if (input->mmwave_online == 0U) {
        mask |= FSM_MODULE_MMWAVE;
    }
    if (input->thz_online == 0U) {
        mask |= FSM_MODULE_THZ;
    }
    if (input->gimbal_online == 0U) {
        mask |= FSM_MODULE_GIMBAL;
    }
    return mask;
}

static uint8_t runtime_state(fsm_state_t state)
{
    return (uint8_t)((state >= FSM_S1_SEARCH) && (state <= FSM_S6_REACQUIRE));
}

static uint8_t target_fresh(const fsm_context_t *ctx, const fsm_input_t *input)
{
    return (uint8_t)(sample_fresh(&input->target_meta, ctx->config.input_max_age_slots) &&
                     (input->target_valid != 0U));
}

static uint8_t target_moved(const fsm_context_t *ctx)
{
    return (uint8_t)(
        (abs_i32(ctx->last_target_azimuth_mdeg - ctx->lock_target_azimuth_mdeg) >
         ctx->config.reacquire_target_delta_mdeg) ||
        (abs_i32(ctx->last_target_elevation_mdeg - ctx->lock_target_elevation_mdeg) >
         ctx->config.reacquire_target_delta_mdeg));
}

static fsm_reason_t run_state(fsm_context_t *ctx, const fsm_input_t *input)
{
    const uint32_t age = input->slot_id - ctx->state_enter_slot;
    const uint8_t target_ok = target_fresh(ctx, input);
    const uint8_t all_healthy = (uint8_t)(ctx->fault_mask == 0U);
    uint8_t condition;

    if (target_ok != 0U) {
        ctx->last_target_azimuth_mdeg = input->target_azimuth_mdeg;
        ctx->last_target_elevation_mdeg = input->target_elevation_mdeg;
    }

    switch (ctx->state) {
    case FSM_S0_SELF_CHECK:
        if (all_healthy != 0U) {
            if (count_condition(ctx, FSM_COUNTER_SELF_OK, 1U) >= ctx->config.self_check_stable_slots) {
                transition(ctx, FSM_S1_SEARCH, input->slot_id);
                return FSM_REASON_SELF_OK;
            }
        } else {
            (void)count_condition(ctx, FSM_COUNTER_SELF_OK, 0U);
        }
        if (age >= ctx->config.self_check_timeout_slots) {
            transition(ctx, FSM_FAULT, input->slot_id);
            return FSM_REASON_SELF_FAIL;
        }
        break;

    case FSM_S1_SEARCH:
        if (count_condition(ctx, FSM_COUNTER_TARGET, target_ok) >= ctx->config.detect_stable_slots) {
            transition(ctx, FSM_S2_COARSE_ALIGN, input->slot_id);
            return FSM_REASON_TARGET_STABLE;
        }
        break;

    case FSM_S2_COARSE_ALIGN:
        if (count_condition(ctx, FSM_COUNTER_TARGET_LOST, (uint8_t)!target_ok) >=
            ctx->config.target_lost_tolerance_slots) {
            transition(ctx, FSM_S1_SEARCH, input->slot_id);
            return FSM_REASON_TARGET_LOST;
        }
        condition = (uint8_t)(sample_fresh(&input->gimbal_meta, ctx->config.input_max_age_slots) &&
                              (input->gimbal_in_position != 0U) &&
                              (input->position_error_mdeg <= ctx->config.position_error_threshold_mdeg));
        if (count_condition(ctx, FSM_COUNTER_ALIGNED, condition) >= ctx->config.coarse_stable_slots) {
            transition(ctx, FSM_S3_CAPTURE, input->slot_id);
            return FSM_REASON_GIMBAL_ALIGNED;
        }
        if (age >= ctx->config.coarse_timeout_slots) {
            transition(ctx, FSM_S1_SEARCH, input->slot_id);
            return FSM_REASON_ALIGN_TIMEOUT;
        }
        break;

    case FSM_S3_CAPTURE:
        condition = (uint8_t)(sample_fresh(&input->thz_meta, ctx->config.input_max_age_slots) &&
                              (input->thz_locked != 0U) &&
                              (input->thz_quality >= ctx->config.thz_quality_threshold));
        if (count_condition(ctx, FSM_COUNTER_CAPTURE_LOCK, condition) >=
            ctx->config.capture_lock_stable_slots) {
            ctx->lock_target_azimuth_mdeg = ctx->last_target_azimuth_mdeg;
            ctx->lock_target_elevation_mdeg = ctx->last_target_elevation_mdeg;
            transition(ctx, FSM_S4_TRACK, input->slot_id);
            return FSM_REASON_THZ_LOCKED;
        }
        if (age >= ctx->config.capture_timeout_slots) {
            transition(ctx, FSM_S5_FALLBACK, input->slot_id);
            return FSM_REASON_CAPTURE_TIMEOUT;
        }
        break;

    case FSM_S4_TRACK:
        condition = (uint8_t)(sample_fresh(&input->thz_meta, ctx->config.input_max_age_slots) &&
                              (input->thz_locked != 0U) &&
                              (input->thz_quality >= ctx->config.thz_quality_threshold));
        if (count_condition(ctx, FSM_COUNTER_TRACK_LOST, (uint8_t)!condition) >=
            ctx->config.tracking_loss_slots) {
            ctx->lock_target_azimuth_mdeg = ctx->last_target_azimuth_mdeg;
            ctx->lock_target_elevation_mdeg = ctx->last_target_elevation_mdeg;
            transition(ctx, FSM_S6_REACQUIRE, input->slot_id);
            return FSM_REASON_TRACK_LOST;
        }
        break;

    case FSM_S5_FALLBACK:
        condition = (uint8_t)(target_ok &&
                              sample_fresh(&input->mmwave_link_meta, ctx->config.input_max_age_slots) &&
                              (input->mmwave_uplink_ready != 0U) &&
                              (input->mmwave_quality >= ctx->config.mmwave_quality_threshold));
        if (count_condition(ctx, FSM_COUNTER_FALLBACK_RECOVER, condition) >=
            ctx->config.fallback_restore_slots) {
            transition(ctx, FSM_S2_COARSE_ALIGN, input->slot_id);
            return FSM_REASON_MMWAVE_RECOVERED;
        }
        if (age >= ctx->config.fallback_timeout_slots) {
            transition(ctx, FSM_S1_SEARCH, input->slot_id);
            return FSM_REASON_FALLBACK_TIMEOUT;
        }
        break;

    case FSM_S6_REACQUIRE:
        if ((target_ok != 0U) && (target_moved(ctx) != 0U)) {
            transition(ctx, FSM_S2_COARSE_ALIGN, input->slot_id);
            return FSM_REASON_REACQUIRE_REALIGN;
        }
        condition = (uint8_t)(sample_fresh(&input->thz_meta, ctx->config.input_max_age_slots) &&
                              (input->thz_locked != 0U) &&
                              (input->thz_quality >= ctx->config.thz_quality_threshold));
        if (count_condition(ctx, FSM_COUNTER_REACQUIRE_LOCK, condition) >=
            ctx->config.reacquire_lock_stable_slots) {
            transition(ctx, FSM_S4_TRACK, input->slot_id);
            return FSM_REASON_REACQUIRE_OK;
        }
        if (age >= ctx->config.reacquire_timeout_slots) {
            transition(ctx, FSM_S5_FALLBACK, input->slot_id);
            return FSM_REASON_REACQUIRE_TIMEOUT;
        }
        break;

    case FSM_S7_MODULE_RECOVERY:
        if (all_healthy != 0U) {
            if (count_condition(ctx, FSM_COUNTER_RECOVERY_OK, 1U) >=
                ctx->config.recovery_stable_slots) {
                ctx->fault_mask = 0U;
                if (target_ok != 0U) {
                    transition(ctx, FSM_S2_COARSE_ALIGN, input->slot_id);
                    return FSM_REASON_RECOVERY_OK_TARGET;
                }
                transition(ctx, FSM_S1_SEARCH, input->slot_id);
                return FSM_REASON_RECOVERY_OK_SEARCH;
            }
        } else {
            (void)count_condition(ctx, FSM_COUNTER_RECOVERY_OK, 0U);
        }
        if ((age != 0U) && (ctx->config.recovery_query_period_slots != 0U) &&
            (age % ctx->config.recovery_query_period_slots == 0U)) {
            if (ctx->recovery_attempts < UINT16_MAX) {
                ctx->recovery_attempts++;
            }
            ctx->last_recovery_action_slot = input->slot_id;
        }
        if ((age >= ctx->config.recovery_timeout_slots) ||
            ((ctx->config.recovery_max_attempts != 0U) &&
             (ctx->recovery_attempts >= ctx->config.recovery_max_attempts))) {
            transition(ctx, FSM_FAULT, input->slot_id);
            return FSM_REASON_RECOVERY_TIMEOUT;
        }
        break;

    default:
        break;
    }
    return FSM_REASON_NONE;
}

static void build_output(const fsm_context_t *ctx, const fsm_input_t *input,
                         fsm_state_t previous, fsm_reason_t reason, fsm_output_t *output)
{
    const uint8_t active = (uint8_t)(ctx->state >= FSM_S1_SEARCH && ctx->state <= FSM_S6_REACQUIRE);
    const uint8_t mmwave_comm = (uint8_t)(ctx->state == FSM_S1_SEARCH ||
                                          ctx->state == FSM_S2_COARSE_ALIGN ||
                                          ctx->state == FSM_S5_FALLBACK);
    memset(output, 0, sizeof(*output));
    output->previous_state = previous;
    output->state = ctx->state;
    output->reason = reason;
    output->fault_mask = ctx->fault_mask;
    if ((ctx->state == FSM_S7_MODULE_RECOVERY) &&
        (ctx->last_recovery_action_slot == input->slot_id)) {
        output->recovery_action_mask = ctx->fault_mask;
    }

    output->mmwave.rf_enable = active;
    output->mmwave.sense_enable = active;
    output->mmwave.comm_enable = mmwave_comm;
    switch (ctx->state) {
    case FSM_S1_SEARCH: output->mmwave.scan_mode = FSM_SCAN_SEARCH; break;
    case FSM_S2_COARSE_ALIGN: output->mmwave.scan_mode = FSM_SCAN_COARSE; break;
    case FSM_S3_CAPTURE: output->mmwave.scan_mode = FSM_SCAN_CAPTURE_ASSIST; break;
    case FSM_S4_TRACK: output->mmwave.scan_mode = FSM_SCAN_ASSIST_TRACKING; break;
    case FSM_S5_FALLBACK: output->mmwave.scan_mode = FSM_SCAN_FALLBACK; break;
    case FSM_S6_REACQUIRE: output->mmwave.scan_mode = FSM_SCAN_REACQUIRE_ASSIST; break;
    default: output->mmwave.scan_mode = FSM_SCAN_IDLE; break;
    }

    output->gimbal.enable = (uint8_t)(ctx->state == FSM_S2_COARSE_ALIGN ||
                                      ctx->state == FSM_S4_TRACK ||
                                      ctx->state == FSM_S6_REACQUIRE);
    output->gimbal.fine_tune_enable = (uint8_t)(ctx->state == FSM_S4_TRACK);
    output->gimbal.target_azimuth_mdeg = ctx->last_target_azimuth_mdeg;
    output->gimbal.target_elevation_mdeg = ctx->last_target_elevation_mdeg;
    output->gimbal.angular_speed_mdeg_s = ctx->config.default_gimbal_speed_mdeg_s;

    output->thz.thz_enable = (uint8_t)(ctx->state == FSM_S3_CAPTURE ||
                                       ctx->state == FSM_S4_TRACK ||
                                       ctx->state == FSM_S6_REACQUIRE);
    output->thz.sense_enable = output->thz.thz_enable;
    output->thz.comm_enable = (uint8_t)(ctx->state == FSM_S4_TRACK);
    output->thz.traffic_enable = output->thz.comm_enable;
    output->thz.reacquire = (uint8_t)(ctx->state == FSM_S6_REACQUIRE);
}

void Fsm_DefaultConfig(fsm_config_t *config)
{
    if (config == NULL) {
        return;
    }
    *config = (fsm_config_t){
        100U, 3U, 2U, 30U, 3U, 2U, 30U, 2U, 500,
        2U, 20U, 400U, 3U, 3U, 30U, 300U, 2U, 20U,
        2000, 3U, 5U, 100U, 3U, 20000
    };
}

void Fsm_Init(fsm_context_t *ctx, const fsm_config_t *config)
{
    fsm_config_t defaults;
    if (ctx == NULL) {
        return;
    }
    Fsm_DefaultConfig(&defaults);
    memset(ctx, 0, sizeof(*ctx));
    ctx->config = (config != NULL) ? *config : defaults;
    ctx->state = FSM_IDLE;
    ctx->previous_state = FSM_IDLE;
}

void Fsm_Step(fsm_context_t *ctx, const fsm_input_t *input, fsm_output_t *output)
{
    fsm_reason_t reason = FSM_REASON_NONE;
    fsm_state_t previous;
    if ((ctx == NULL) || (input == NULL) || (output == NULL)) {
        return;
    }
    previous = ctx->state;
    if (input->reset != 0U) {
        ctx->state = FSM_IDLE;
        ctx->state_enter_slot = input->slot_id;
        ctx->fault_mask = 0U;
        ctx->recovery_attempts = 0U;
        clear_counters(ctx);
        reason = FSM_REASON_RESET;
    } else if (ctx->state == FSM_IDLE) {
        if (input->start != 0U) {
            transition(ctx, FSM_S0_SELF_CHECK, input->slot_id);
            reason = FSM_REASON_START;
        }
    } else if (ctx->state != FSM_FAULT) {
        ctx->fault_mask = health_fault_mask(input);
        if ((runtime_state(ctx->state) != 0U) && (ctx->fault_mask != 0U)) {
            transition(ctx, FSM_S7_MODULE_RECOVERY, input->slot_id);
            ctx->recovery_attempts = 0U;
            ctx->last_recovery_action_slot = input->slot_id;
            reason = FSM_REASON_MODULE_FAULT;
        } else {
            reason = run_state(ctx, input);
        }
    }
    build_output(ctx, input, previous, reason, output);
    ctx->previous_state = previous;
}

const char *Fsm_StateName(fsm_state_t state)
{
    static const char *const names[] = {"IDLE", "FAULT", "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"};
    return ((unsigned)state < (sizeof(names) / sizeof(names[0]))) ? names[state] : "UNKNOWN";
}

const char *Fsm_ReasonName(fsm_reason_t reason)
{
    static const char *const names[] = {
        "NONE", "START", "RESET", "SELF_OK", "SELF_FAIL", "TARGET_STABLE",
        "TARGET_LOST", "GIMBAL_ALIGNED", "ALIGN_TIMEOUT", "THZ_LOCKED",
        "CAPTURE_TIMEOUT", "TRACK_LOST", "REACQUIRE_OK", "REACQUIRE_TIMEOUT",
        "REACQUIRE_REALIGN", "MMWAVE_RECOVERED", "FALLBACK_TIMEOUT",
        "MODULE_FAULT", "RECOVERY_OK_TARGET", "RECOVERY_OK_SEARCH", "RECOVERY_TIMEOUT"
    };
    return ((unsigned)reason < (sizeof(names) / sizeof(names[0]))) ? names[reason] : "UNKNOWN";
}

const char *Fsm_ScanModeName(fsm_scan_mode_t mode)
{
    static const char *const names[] = {
        "idle", "search", "coarse", "capture_assist", "assist_tracking",
        "fallback", "reacquire_assist"
    };
    return ((unsigned)mode < (sizeof(names) / sizeof(names[0]))) ? names[mode] : "unknown";
}
