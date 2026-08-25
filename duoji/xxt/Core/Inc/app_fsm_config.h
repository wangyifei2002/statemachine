#ifndef APP_FSM_CONFIG_H
#define APP_FSM_CONFIG_H

#define SLOT_PERIOD_MS                       200U
#define SELF_CHECK_PASS_SLOTS                3U
#define SELF_CHECK_TIMEOUT_MS                10000U
#define MM_STABLE_SLOTS                      3U
#define GIMBAL_READY_SLOTS                   2U
#define COARSE_ALIGN_TIMEOUT_MS              8000U
#define CAPTURE_TIMEOUT_MS                   6000U
#define TRACK_BAD_SLOTS                      3U
#define TRACK_REALIGN_AZ_DELTA_DEG           2
#define TRACK_REALIGN_EL_DELTA_DEG           2
#define FALLBACK_RECOVER_STABLE_SLOTS        3U
#define FALLBACK_NO_RECOVER_TIMEOUT_MS       4000U
#define FALLBACK_QBAD_CLEAR_TIMEOUT_MS       2000U
#define REACQUIRE_TIMEOUT_MS                 2000U
#define REACQUIRE_LOCK_STABLE_SLOTS          2U
#define REACQUIRE_CMD_INTERVAL_MS            600U
#define REACQUIRE_CMD_MAX_SENDS              3U
#define REACQUIRE_MAX_AZ_DELTA_DEG           2
#define REACQUIRE_MAX_EL_DELTA_DEG           2
#define RECOVERY_QUERY_PERIOD_MS             500U
#define RECOVERY_TIMEOUT_MS                  10000U
#define RECOVERY_MAX_ATTEMPTS                3U
#define RECOVERY_REENTRY_WINDOW_MS           60000U
#define RECOVERY_REENTRY_MAX                 3U

#if (SLOT_PERIOD_MS == 0U) || (RECOVERY_MAX_ATTEMPTS == 0U)
#error "FSM timing and retry parameters must be greater than zero"
#endif

#if (REACQUIRE_CMD_MAX_SENDS == 0U) || (REACQUIRE_TIMEOUT_MS == 0U)
#error "S6 command count and timeout must be greater than zero"
#endif

#endif
