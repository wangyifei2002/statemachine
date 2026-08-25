#ifndef APP_FSM_H
#define APP_FSM_H

#include <stdint.h>
#include "app_device.h"
#include "app_events.h"

typedef enum
{
    S_IDLE = 0,
    S_FAULT,
    S0_SELF_CHECK,
    S1_SEARCH,
    S2_COARSE_ALIGN,
    S3_CAPTURE,
    S4_TRACK,
    S5_FALLBACK,
    S6_REACQUIRE,
    S7_MODULE_RECOVERY
} fsm_state_t;

typedef void (*app_log_line_fn_t)(const char *text);

typedef struct
{
    /* All callbacks execute in the main loop. Return 1 when accepted. */
    void (*stop_active_operations)(void);
    uint8_t (*set_gimbal_target)(int16_t az_deg, int16_t el_deg);
    uint8_t (*send_thz_reacquire)(void);
    uint8_t (*query_module)(app_module_t module);
    uint8_t (*recover_module)(app_module_t module, uint32_t attempt);
    uint8_t (*reapply_module_config)(app_module_t module);
} app_fsm_actions_t;

void App_Fsm_Init(uint32_t now, app_log_line_fn_t log_fn);
void App_Fsm_SetActions(const app_fsm_actions_t *actions);
void App_Fsm_Run(uint32_t now);
void App_Fsm_ProcessEvents(uint32_t now);
void App_Fsm_PostEvent(app_event_t event);
void App_Fsm_PostHealthEvent(app_event_t event);
void App_Fsm_Reset(uint32_t now, uint8_t clear_simulated_inputs);

fsm_state_t App_Fsm_GetState(void);
uint32_t App_Fsm_GetSlotCount(void);
uint32_t App_Fsm_GetEventFlags(void);
uint32_t App_Fsm_GetFaultModuleMask(void);
uint8_t App_Fsm_IsRuntimeState(void);

const char *App_Fsm_StateToString(fsm_state_t state);
const char *App_Fsm_EventToString(app_event_t event);
void App_Fsm_PrintStatus(void);

#endif
