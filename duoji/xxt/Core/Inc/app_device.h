#ifndef APP_DEVICE_H
#define APP_DEVICE_H

#include <stdint.h>

typedef enum
{
    APP_MODULE_BBU = 0,
    APP_MODULE_THZ,
    APP_MODULE_GIMBAL,
    APP_MODULE_COUNT
} app_module_t;

#define APP_MODULE_MASK_BBU       (1UL << APP_MODULE_BBU)
#define APP_MODULE_MASK_THZ       (1UL << APP_MODULE_THZ)
#define APP_MODULE_MASK_GIMBAL    (1UL << APP_MODULE_GIMBAL)

typedef struct
{
    uint8_t bbu_online;
    uint8_t bbu_ready;
    uint8_t bbu_data_fresh;

    uint8_t thz_online;
    uint8_t thz_ready;

    uint8_t gimbal_online;
    uint8_t gimbal_module_ready;
    uint8_t gimbal_error;

    uint8_t mm_target_valid;
    int16_t target_az_deg;
    int16_t target_el_deg;
    uint8_t gimbal_ready;
    uint8_t thz_locked;
    uint8_t thz_quality_bad;

    uint32_t bbu_data_seq;
    uint32_t gimbal_status_seq;
    uint32_t thz_status_seq;
    uint32_t bbu_last_response_tick;
    uint32_t bbu_last_data_tick;
    uint32_t thz_last_response_tick;
    uint32_t gimbal_last_response_tick;
} app_device_snapshot_t;

#endif
