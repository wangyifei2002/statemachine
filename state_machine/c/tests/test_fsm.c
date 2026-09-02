#include "fsm.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static fsm_input_t healthy_input(uint32_t slot)
{
    fsm_input_t input;
    memset(&input, 0, sizeof(input));
    input.slot_id = slot;
    input.mmwave_online = 1U;
    input.thz_online = 1U;
    input.gimbal_online = 1U;
    input.target_meta.valid = 1U;
    input.target_meta.seq = slot;
    input.mmwave_link_meta.valid = 1U;
    input.mmwave_link_meta.seq = slot;
    input.gimbal_meta.valid = 1U;
    input.gimbal_meta.seq = slot;
    input.thz_meta.valid = 1U;
    input.thz_meta.seq = slot;
    input.target_azimuth_mdeg = 12000;
    input.target_elevation_mdeg = 2000;
    input.position_error_mdeg = 5000;
    input.thz_quality = 900U;
    input.mmwave_quality = 800U;
    input.mmwave_uplink_ready = 1U;
    return input;
}

static void short_config(fsm_config_t *config)
{
    Fsm_DefaultConfig(config);
    config->self_check_stable_slots = 1U;
    config->detect_stable_slots = 1U;
    config->coarse_stable_slots = 1U;
    config->capture_lock_stable_slots = 1U;
    config->tracking_loss_slots = 2U;
    config->fallback_restore_slots = 2U;
    config->reacquire_lock_stable_slots = 1U;
    config->recovery_stable_slots = 2U;
    config->recovery_query_period_slots = 10U;
}

static uint32_t reach_tracking(fsm_context_t *ctx)
{
    fsm_input_t input;
    fsm_output_t output;
    uint32_t slot = 1U;
    input = healthy_input(slot);
    input.start = 1U;
    Fsm_Step(ctx, &input, &output);
    assert(output.state == FSM_S0_SELF_CHECK);

    input = healthy_input(++slot);
    Fsm_Step(ctx, &input, &output);
    assert(output.state == FSM_S1_SEARCH);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    Fsm_Step(ctx, &input, &output);
    assert(output.state == FSM_S2_COARSE_ALIGN);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    input.gimbal_in_position = 1U;
    input.position_error_mdeg = 100;
    Fsm_Step(ctx, &input, &output);
    assert(output.state == FSM_S3_CAPTURE);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    input.gimbal_in_position = 1U;
    input.position_error_mdeg = 100;
    input.thz_locked = 1U;
    Fsm_Step(ctx, &input, &output);
    assert(output.state == FSM_S4_TRACK);
    return slot;
}

static void test_fast_reacquire(void)
{
    fsm_config_t config;
    fsm_context_t ctx;
    fsm_input_t input;
    fsm_output_t output;
    uint32_t slot;
    short_config(&config);
    Fsm_Init(&ctx, &config);
    slot = reach_tracking(&ctx);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    Fsm_Step(&ctx, &input, &output);
    assert(output.state == FSM_S4_TRACK);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    Fsm_Step(&ctx, &input, &output);
    assert(output.state == FSM_S6_REACQUIRE);
    assert(output.reason == FSM_REASON_TRACK_LOST);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    input.thz_locked = 1U;
    Fsm_Step(&ctx, &input, &output);
    assert(output.state == FSM_S4_TRACK);
    assert(output.reason == FSM_REASON_REACQUIRE_OK);
}

static void test_module_recovery_and_reset(void)
{
    fsm_config_t config;
    fsm_context_t ctx;
    fsm_input_t input;
    fsm_output_t output;
    uint32_t slot;
    short_config(&config);
    Fsm_Init(&ctx, &config);
    slot = reach_tracking(&ctx);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    input.thz_online = 0U;
    Fsm_Step(&ctx, &input, &output);
    assert(output.state == FSM_S7_MODULE_RECOVERY);
    assert(output.reason == FSM_REASON_MODULE_FAULT);
    assert(output.fault_mask == FSM_MODULE_THZ);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    Fsm_Step(&ctx, &input, &output);
    assert(output.state == FSM_S7_MODULE_RECOVERY);
    input = healthy_input(++slot);
    input.target_valid = 1U;
    Fsm_Step(&ctx, &input, &output);
    assert(output.state == FSM_S2_COARSE_ALIGN);
    assert(output.reason == FSM_REASON_RECOVERY_OK_TARGET);

    ctx.state = FSM_FAULT;
    input = healthy_input(++slot);
    input.reset = 1U;
    Fsm_Step(&ctx, &input, &output);
    assert(output.state == FSM_IDLE);
    assert(output.reason == FSM_REASON_RESET);
}

static void test_stale_target_and_output_units(void)
{
    fsm_config_t config;
    fsm_context_t ctx;
    fsm_input_t input;
    fsm_output_t output;
    short_config(&config);
    Fsm_Init(&ctx, &config);
    input = healthy_input(1U);
    input.start = 1U;
    Fsm_Step(&ctx, &input, &output);
    input = healthy_input(2U);
    Fsm_Step(&ctx, &input, &output);
    input = healthy_input(3U);
    input.target_valid = 1U;
    input.target_meta.age_slots = (uint16_t)(config.input_max_age_slots + 1U);
    Fsm_Step(&ctx, &input, &output);
    assert(output.state == FSM_S1_SEARCH);
    assert(output.gimbal.angular_speed_mdeg_s == 20000);
}

int main(void)
{
    test_fast_reacquire();
    test_module_recovery_and_reset();
    test_stale_target_and_output_units();
    puts("C FSM tests passed");
    return 0;
}
