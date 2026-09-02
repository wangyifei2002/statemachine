#ifndef UNIFIED_FSM_H
#define UNIFIED_FSM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    FSM_IDLE = 0,
    FSM_FAULT = 1,
    FSM_S0_SELF_CHECK = 2,
    FSM_S1_SEARCH = 3,
    FSM_S2_COARSE_ALIGN = 4,
    FSM_S3_CAPTURE = 5,
    FSM_S4_TRACK = 6,
    FSM_S5_FALLBACK = 7,
    FSM_S6_REACQUIRE = 8,
    FSM_S7_MODULE_RECOVERY = 9
} fsm_state_t;

typedef enum {
    FSM_REASON_NONE = 0,
    FSM_REASON_START,
    FSM_REASON_RESET,
    FSM_REASON_SELF_OK,
    FSM_REASON_SELF_FAIL,
    FSM_REASON_TARGET_STABLE,
    FSM_REASON_TARGET_LOST,
    FSM_REASON_GIMBAL_ALIGNED,
    FSM_REASON_ALIGN_TIMEOUT,
    FSM_REASON_THZ_LOCKED,
    FSM_REASON_CAPTURE_TIMEOUT,
    FSM_REASON_TRACK_LOST,
    FSM_REASON_REACQUIRE_OK,
    FSM_REASON_REACQUIRE_TIMEOUT,
    FSM_REASON_REACQUIRE_REALIGN,
    FSM_REASON_MMWAVE_RECOVERED,
    FSM_REASON_FALLBACK_TIMEOUT,
    FSM_REASON_MODULE_FAULT,
    FSM_REASON_RECOVERY_OK_TARGET,
    FSM_REASON_RECOVERY_OK_SEARCH,
    FSM_REASON_RECOVERY_TIMEOUT
} fsm_reason_t;

enum {
    FSM_MODULE_MMWAVE = 1U << 0,
    FSM_MODULE_THZ = 1U << 1,
    FSM_MODULE_GIMBAL = 1U << 2
};

typedef enum {
    FSM_SCAN_IDLE = 0,
    FSM_SCAN_SEARCH,
    FSM_SCAN_COARSE,
    FSM_SCAN_CAPTURE_ASSIST,
    FSM_SCAN_ASSIST_TRACKING,
    FSM_SCAN_FALLBACK,
    FSM_SCAN_REACQUIRE_ASSIST
} fsm_scan_mode_t;

typedef struct {
    uint32_t slot_period_ms;
    uint16_t input_max_age_slots;
    uint16_t self_check_stable_slots;
    uint16_t self_check_timeout_slots;
    uint16_t detect_stable_slots;
    uint16_t coarse_stable_slots;
    uint16_t coarse_timeout_slots;
    uint16_t target_lost_tolerance_slots;
    int32_t position_error_threshold_mdeg;
    uint16_t capture_lock_stable_slots;
    uint16_t capture_timeout_slots;
    uint16_t thz_quality_threshold;
    uint16_t tracking_loss_slots;
    uint16_t fallback_restore_slots;
    uint16_t fallback_timeout_slots;
    uint16_t mmwave_quality_threshold;
    uint16_t reacquire_lock_stable_slots;
    uint16_t reacquire_timeout_slots;
    int32_t reacquire_target_delta_mdeg;
    uint16_t recovery_stable_slots;
    uint16_t recovery_query_period_slots;
    uint16_t recovery_timeout_slots;
    uint16_t recovery_max_attempts;
    int32_t default_gimbal_speed_mdeg_s;
} fsm_config_t;

typedef struct {
    uint8_t valid;
    uint32_t seq;
    uint16_t age_slots;
} fsm_sample_meta_t;

typedef struct {
    uint32_t slot_id;
    uint8_t start;
    uint8_t reset;
    uint32_t explicit_fault_mask;
    uint8_t mmwave_online;
    uint8_t thz_online;
    uint8_t gimbal_online;

    fsm_sample_meta_t target_meta;
    uint8_t target_valid;
    int32_t target_azimuth_mdeg;
    int32_t target_elevation_mdeg;

    fsm_sample_meta_t mmwave_link_meta;
    uint8_t mmwave_uplink_ready;
    uint16_t mmwave_quality;

    fsm_sample_meta_t gimbal_meta;
    uint8_t gimbal_in_position;
    int32_t position_error_mdeg;

    fsm_sample_meta_t thz_meta;
    uint8_t thz_locked;
    uint16_t thz_quality;
} fsm_input_t;

typedef struct {
    uint8_t rf_enable;
    uint8_t sense_enable;
    uint8_t comm_enable;
    fsm_scan_mode_t scan_mode;
} fsm_mmwave_command_t;

typedef struct {
    uint8_t enable;
    uint8_t fine_tune_enable;
    int32_t target_azimuth_mdeg;
    int32_t target_elevation_mdeg;
    int32_t angular_speed_mdeg_s;
} fsm_gimbal_command_t;

typedef struct {
    uint8_t thz_enable;
    uint8_t sense_enable;
    uint8_t comm_enable;
    uint8_t traffic_enable;
    uint8_t reacquire;
} fsm_thz_command_t;

typedef struct {
    fsm_state_t previous_state;
    fsm_state_t state;
    fsm_reason_t reason;
    uint32_t fault_mask;
    uint32_t recovery_action_mask;
    fsm_mmwave_command_t mmwave;
    fsm_gimbal_command_t gimbal;
    fsm_thz_command_t thz;
} fsm_output_t;

typedef enum {
    FSM_COUNTER_SELF_OK = 0,
    FSM_COUNTER_TARGET,
    FSM_COUNTER_TARGET_LOST,
    FSM_COUNTER_ALIGNED,
    FSM_COUNTER_CAPTURE_LOCK,
    FSM_COUNTER_TRACK_LOST,
    FSM_COUNTER_FALLBACK_RECOVER,
    FSM_COUNTER_REACQUIRE_LOCK,
    FSM_COUNTER_RECOVERY_OK,
    FSM_COUNTER_COUNT
} fsm_counter_t;

typedef struct {
    fsm_config_t config;
    fsm_state_t state;
    fsm_state_t previous_state;
    uint32_t state_enter_slot;
    uint32_t fault_mask;
    int32_t last_target_azimuth_mdeg;
    int32_t last_target_elevation_mdeg;
    int32_t lock_target_azimuth_mdeg;
    int32_t lock_target_elevation_mdeg;
    uint16_t counters[FSM_COUNTER_COUNT];
    uint16_t recovery_attempts;
    uint32_t last_recovery_action_slot;
} fsm_context_t;

void Fsm_DefaultConfig(fsm_config_t *config);
void Fsm_Init(fsm_context_t *ctx, const fsm_config_t *config);
void Fsm_Step(fsm_context_t *ctx, const fsm_input_t *input, fsm_output_t *output);

const char *Fsm_StateName(fsm_state_t state);
const char *Fsm_ReasonName(fsm_reason_t reason);
const char *Fsm_ScanModeName(fsm_scan_mode_t mode);

#ifdef __cplusplus
}
#endif

#endif
