#include "app_health_monitor.h"

#include <string.h>

#define HEALTH_MONITOR_PERIOD_MS          200U
#define HEALTH_OFFLINE_CONFIRM_COUNT      5U
#define HEALTH_RECOVER_CONFIRM_COUNT      3U
#define BBU_DATA_STALE_MS                 1000U

typedef struct
{
    uint8_t sim_responding;
    uint8_t sim_ready;
    uint8_t online;
    uint8_t ready;
    uint8_t ever_online;
    uint8_t offline_latched;
    uint8_t ready_fault_latched;
    uint8_t response_seen;
    uint8_t success_count;
    uint8_t miss_count;
    uint8_t not_ready_count;
    uint8_t ready_recover_count;
    uint32_t last_response_tick;
} module_monitor_t;

static module_monitor_t g_modules[APP_MODULE_COUNT];
static app_device_snapshot_t g_snapshot;
static uint32_t g_last_monitor_tick;

static uint8_t g_sim_bbu_data_streaming;
static uint8_t g_sim_target_valid;
static int16_t g_sim_target_az_deg;
static int16_t g_sim_target_el_deg;
static uint8_t g_sim_gimbal_ready;
static uint8_t g_sim_thz_locked;
static uint8_t g_sim_thz_quality_bad;
static uint8_t g_sim_gimbal_error;

static uint8_t g_bbu_data_stale_latched;
static uint8_t g_bbu_fresh_count;
static uint8_t g_gimbal_error_latched;
static uint8_t g_gimbal_error_recover_count;
static app_health_event_sink_t g_event_sink;
static uint8_t g_use_external_samples;
static uint8_t g_external_bbu_data_seen;

static void health_post_event(app_event_t event)
{
    if (g_event_sink != 0)
    {
        g_event_sink(event);
    }
}

static app_event_t module_offline_event(app_module_t module)
{
    switch (module)
    {
    case APP_MODULE_BBU:    return EVT_BBU_OFFLINE;
    case APP_MODULE_THZ:    return EVT_THZ_OFFLINE;
    case APP_MODULE_GIMBAL: return EVT_GIMBAL_OFFLINE;
    default:                return EVT_NONE;
    }
}

static app_event_t module_recovered_event(app_module_t module)
{
    switch (module)
    {
    case APP_MODULE_BBU:    return EVT_BBU_RECOVERED;
    case APP_MODULE_THZ:    return EVT_THZ_RECOVERED;
    case APP_MODULE_GIMBAL: return EVT_GIMBAL_RECOVERED;
    default:                return EVT_NONE;
    }
}

static app_event_t module_not_ready_event(app_module_t module)
{
    switch (module)
    {
    case APP_MODULE_BBU:    return EVT_BBU_NOT_READY;
    case APP_MODULE_THZ:    return EVT_THZ_NOT_READY;
    case APP_MODULE_GIMBAL: return EVT_GIMBAL_NOT_READY;
    default:                return EVT_NONE;
    }
}

static void update_module(app_module_t module,
                          uint8_t responding,
                          uint32_t now)
{
    module_monitor_t *monitor = &g_modules[module];

    if (responding)
    {
        monitor->miss_count = 0U;
        if (monitor->success_count < HEALTH_RECOVER_CONFIRM_COUNT)
        {
            monitor->success_count++;
        }
        monitor->last_response_tick = now;

        if ((!monitor->online) &&
            (monitor->success_count >= HEALTH_RECOVER_CONFIRM_COUNT))
        {
            monitor->online = 1U;
            monitor->ever_online = 1U;
            if (monitor->offline_latched)
            {
                monitor->offline_latched = 0U;
                health_post_event(module_recovered_event(module));
            }
        }
    }
    else
    {
        monitor->success_count = 0U;
        if (monitor->miss_count < HEALTH_OFFLINE_CONFIRM_COUNT)
        {
            monitor->miss_count++;
        }

        if (monitor->online &&
            (monitor->miss_count >= HEALTH_OFFLINE_CONFIRM_COUNT))
        {
            monitor->online = 0U;
            monitor->offline_latched = 1U;
            health_post_event(module_offline_event(module));
        }
    }

    if (!monitor->online)
    {
        monitor->not_ready_count = 0U;
        monitor->ready_recover_count = 0U;
    }
    else if (!monitor->sim_ready)
    {
        monitor->ready_recover_count = 0U;
        if (monitor->not_ready_count < HEALTH_RECOVER_CONFIRM_COUNT)
        {
            monitor->not_ready_count++;
        }
        if ((!monitor->ready_fault_latched) &&
            (monitor->not_ready_count >= HEALTH_RECOVER_CONFIRM_COUNT))
        {
            monitor->ready_fault_latched = 1U;
            health_post_event(module_not_ready_event(module));
        }
    }
    else
    {
        monitor->not_ready_count = 0U;
        if (monitor->ready_fault_latched)
        {
            if (monitor->ready_recover_count <
                HEALTH_RECOVER_CONFIRM_COUNT)
            {
                monitor->ready_recover_count++;
            }
            if (monitor->ready_recover_count >=
                HEALTH_RECOVER_CONFIRM_COUNT)
            {
                monitor->ready_fault_latched = 0U;
                monitor->ready_recover_count = 0U;
                health_post_event(module_recovered_event(module));
            }
        }
    }

    monitor->ready = (uint8_t)(monitor->online &&
                               monitor->sim_ready &&
                               (!monitor->ready_fault_latched));
}

static void update_bbu_data(uint32_t now)
{
    uint8_t data_arrived;

    if (!g_modules[APP_MODULE_BBU].online)
    {
        g_snapshot.bbu_data_fresh = 0U;
        g_bbu_fresh_count = 0U;
        return;
    }

    data_arrived = g_use_external_samples ?
                   g_external_bbu_data_seen :
                   g_sim_bbu_data_streaming;
    g_external_bbu_data_seen = 0U;

    if (data_arrived)
    {
        g_snapshot.bbu_last_data_tick = now;
        g_snapshot.bbu_data_seq++;

        if (!g_snapshot.bbu_data_fresh)
        {
            if (g_bbu_fresh_count < HEALTH_RECOVER_CONFIRM_COUNT)
            {
                g_bbu_fresh_count++;
            }
            if (g_bbu_fresh_count >= HEALTH_RECOVER_CONFIRM_COUNT)
            {
                g_snapshot.bbu_data_fresh = 1U;
                if (g_bbu_data_stale_latched)
                {
                    g_bbu_data_stale_latched = 0U;
                    health_post_event(EVT_BBU_RECOVERED);
                }
            }
        }
    }
    else
    {
        g_bbu_fresh_count = 0U;
        if (g_snapshot.bbu_data_fresh &&
            ((now - g_snapshot.bbu_last_data_tick) >= BBU_DATA_STALE_MS))
        {
            g_snapshot.bbu_data_fresh = 0U;
            g_bbu_data_stale_latched = 1U;
            health_post_event(EVT_BBU_DATA_STALE);
        }
    }
}

static void update_gimbal_error(void)
{
    if (g_sim_gimbal_error)
    {
        g_gimbal_error_recover_count = 0U;
        if (!g_gimbal_error_latched)
        {
            g_gimbal_error_latched = 1U;
            health_post_event(EVT_GIMBAL_ERROR);
        }
    }
    else if (g_gimbal_error_latched &&
             g_modules[APP_MODULE_GIMBAL].online &&
             g_modules[APP_MODULE_GIMBAL].ready)
    {
        if (g_gimbal_error_recover_count < HEALTH_RECOVER_CONFIRM_COUNT)
        {
            g_gimbal_error_recover_count++;
        }
        if (g_gimbal_error_recover_count >= HEALTH_RECOVER_CONFIRM_COUNT)
        {
            g_gimbal_error_latched = 0U;
            health_post_event(EVT_GIMBAL_RECOVERED);
        }
    }

    g_snapshot.gimbal_error = g_gimbal_error_latched ? 1U : 0U;
}

void App_HealthMonitor_Init(uint32_t now,
                            app_health_event_sink_t event_sink)
{
    g_event_sink = event_sink;
    App_HealthMonitor_ResetSimulation(now);
}

void App_HealthMonitor_ResetSimulation(uint32_t now)
{
    uint32_t i;

    memset(g_modules, 0, sizeof(g_modules));
    memset(&g_snapshot, 0, sizeof(g_snapshot));

    for (i = 0U; i < APP_MODULE_COUNT; i++)
    {
        g_modules[i].last_response_tick = now;
    }

    g_last_monitor_tick = now;
    g_snapshot.bbu_last_data_tick = now;
    g_sim_bbu_data_streaming = 0U;
    g_sim_target_valid = 0U;
    g_sim_target_az_deg = 0;
    g_sim_target_el_deg = 0;
    g_sim_gimbal_ready = 0U;
    g_sim_thz_locked = 0U;
    g_sim_thz_quality_bad = 0U;
    g_sim_gimbal_error = 0U;
    g_bbu_data_stale_latched = 0U;
    g_bbu_fresh_count = 0U;
    g_gimbal_error_latched = 0U;
    g_gimbal_error_recover_count = 0U;
    g_use_external_samples = 0U;
    g_external_bbu_data_seen = 0U;
}

void App_HealthMonitor_Run(uint32_t now)
{
    uint32_t i;

    if ((now - g_last_monitor_tick) < HEALTH_MONITOR_PERIOD_MS)
    {
        return;
    }
    g_last_monitor_tick = now;

    for (i = 0U; i < APP_MODULE_COUNT; i++)
    {
        update_module((app_module_t)i,
                      g_use_external_samples ?
                      g_modules[i].response_seen :
                      g_modules[i].sim_responding,
                      now);
        g_modules[i].response_seen = 0U;
    }

    g_snapshot.bbu_online = g_modules[APP_MODULE_BBU].online;
    g_snapshot.bbu_ready = g_modules[APP_MODULE_BBU].ready;
    g_snapshot.thz_online = g_modules[APP_MODULE_THZ].online;
    g_snapshot.thz_ready = g_modules[APP_MODULE_THZ].ready;
    g_snapshot.gimbal_online = g_modules[APP_MODULE_GIMBAL].online;
    g_snapshot.gimbal_module_ready = g_modules[APP_MODULE_GIMBAL].ready;

    g_snapshot.bbu_last_response_tick =
        g_modules[APP_MODULE_BBU].last_response_tick;
    g_snapshot.thz_last_response_tick =
        g_modules[APP_MODULE_THZ].last_response_tick;
    g_snapshot.gimbal_last_response_tick =
        g_modules[APP_MODULE_GIMBAL].last_response_tick;

    update_bbu_data(now);
    update_gimbal_error();

    g_snapshot.mm_target_valid = g_sim_target_valid;
    g_snapshot.target_az_deg = g_sim_target_az_deg;
    g_snapshot.target_el_deg = g_sim_target_el_deg;
    g_snapshot.gimbal_ready = g_sim_gimbal_ready;
    g_snapshot.thz_locked = g_sim_thz_locked;
    g_snapshot.thz_quality_bad = g_sim_thz_quality_bad;

    if ((!g_use_external_samples) &&
        g_modules[APP_MODULE_GIMBAL].online)
    {
        g_snapshot.gimbal_status_seq++;
    }
    if ((!g_use_external_samples) &&
        g_modules[APP_MODULE_THZ].online)
    {
        g_snapshot.thz_status_seq++;
    }
}

const app_device_snapshot_t *App_HealthMonitor_GetSnapshot(void)
{
    return &g_snapshot;
}

void App_HealthMonitor_UseExternalSamples(uint8_t enable, uint32_t now)
{
    uint32_t i;

    g_use_external_samples = enable ? 1U : 0U;
    g_external_bbu_data_seen = 0U;
    for (i = 0U; i < APP_MODULE_COUNT; i++)
    {
        g_modules[i].response_seen = 0U;
        g_modules[i].success_count = 0U;
        g_modules[i].miss_count = 0U;
        g_modules[i].last_response_tick = now;
    }
    g_snapshot.bbu_last_data_tick = now;
}

void App_HealthMonitor_ReportModuleStatus(app_module_t module,
                                          uint8_t ready,
                                          uint32_t now)
{
    if ((!g_use_external_samples) || (module >= APP_MODULE_COUNT))
    {
        return;
    }
    g_modules[module].response_seen = 1U;
    g_modules[module].sim_ready = ready ? 1U : 0U;
    g_modules[module].last_response_tick = now;
}

void App_HealthMonitor_ReportBbuTarget(uint8_t valid,
                                       int16_t az_deg,
                                       int16_t el_deg,
                                       uint32_t now)
{
    if (!g_use_external_samples)
    {
        return;
    }
    g_sim_target_valid = valid ? 1U : 0U;
    g_sim_target_az_deg = az_deg;
    g_sim_target_el_deg = el_deg;
    g_snapshot.bbu_last_data_tick = now;
    g_external_bbu_data_seen = 1U;
}

void App_HealthMonitor_ReportGimbalStatus(uint8_t position_ready,
                                          uint8_t error)
{
    if (!g_use_external_samples)
    {
        return;
    }
    g_sim_gimbal_ready = position_ready ? 1U : 0U;
    g_sim_gimbal_error = error ? 1U : 0U;
    g_snapshot.gimbal_status_seq++;
}

void App_HealthMonitor_ReportThzStatus(uint8_t locked,
                                       uint8_t quality_bad)
{
    if (!g_use_external_samples)
    {
        return;
    }
    g_sim_thz_locked = locked ? 1U : 0U;
    g_sim_thz_quality_bad = quality_bad ? 1U : 0U;
    g_snapshot.thz_status_seq++;
}

void App_HealthMonitor_SimSetLink(app_module_t module, uint8_t on, uint32_t now)
{
    if (module >= APP_MODULE_COUNT)
    {
        return;
    }

    g_modules[module].sim_responding = on ? 1U : 0U;
    if (on)
    {
        g_modules[module].sim_ready = 1U;
        g_modules[module].last_response_tick = now;
        if (module == APP_MODULE_BBU)
        {
            g_sim_bbu_data_streaming = 1U;
            g_snapshot.bbu_last_data_tick = now;
        }
    }
}

void App_HealthMonitor_SimSetModuleReady(app_module_t module, uint8_t ready)
{
    if (module < APP_MODULE_COUNT)
    {
        g_modules[module].sim_ready = ready ? 1U : 0U;
    }
}

void App_HealthMonitor_SimSetBbuDataStreaming(uint8_t on, uint32_t now)
{
    g_sim_bbu_data_streaming = on ? 1U : 0U;
    if (on)
    {
        g_snapshot.bbu_last_data_tick = now;
        g_bbu_fresh_count = 0U;
    }
}

void App_HealthMonitor_SimSetTargetValid(uint8_t valid)
{
    g_sim_target_valid = valid ? 1U : 0U;
}

void App_HealthMonitor_SimSetTargetAngle(int16_t az_deg, int16_t el_deg)
{
    g_sim_target_az_deg = az_deg;
    g_sim_target_el_deg = el_deg;
}

void App_HealthMonitor_SimSetGimbalReady(uint8_t ready)
{
    g_sim_gimbal_ready = ready ? 1U : 0U;
}

void App_HealthMonitor_SimSetThzLocked(uint8_t locked)
{
    g_sim_thz_locked = locked ? 1U : 0U;
}

void App_HealthMonitor_SimSetThzQualityBad(uint8_t bad)
{
    g_sim_thz_quality_bad = bad ? 1U : 0U;
}

void App_HealthMonitor_SimSetGimbalError(uint8_t error)
{
    g_sim_gimbal_error = error ? 1U : 0U;
}
