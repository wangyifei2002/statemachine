#ifndef APP_HEALTH_MONITOR_H
#define APP_HEALTH_MONITOR_H

#include <stdint.h>
#include "app_device.h"
#include "app_events.h"

typedef void (*app_health_event_sink_t)(app_event_t event);

void App_HealthMonitor_Init(uint32_t now,
                            app_health_event_sink_t event_sink);
void App_HealthMonitor_Run(uint32_t now);
const app_device_snapshot_t *App_HealthMonitor_GetSnapshot(void);

/* Real protocol adapters call these from the main-loop parser, not from ISR. */
void App_HealthMonitor_UseExternalSamples(uint8_t enable, uint32_t now);
void App_HealthMonitor_ReportModuleStatus(app_module_t module,
                                          uint8_t ready,
                                          uint32_t now);
void App_HealthMonitor_ReportBbuTarget(uint8_t valid,
                                       int16_t az_deg,
                                       int16_t el_deg,
                                       uint32_t now);
void App_HealthMonitor_ReportGimbalStatus(uint8_t position_ready,
                                          uint8_t error);
void App_HealthMonitor_ReportThzStatus(uint8_t locked,
                                       uint8_t quality_bad);

void App_HealthMonitor_SimSetLink(app_module_t module, uint8_t on, uint32_t now);
void App_HealthMonitor_SimSetModuleReady(app_module_t module, uint8_t ready);
void App_HealthMonitor_SimSetBbuDataStreaming(uint8_t on, uint32_t now);
void App_HealthMonitor_SimSetTargetValid(uint8_t valid);
void App_HealthMonitor_SimSetTargetAngle(int16_t az_deg, int16_t el_deg);
void App_HealthMonitor_SimSetGimbalReady(uint8_t ready);
void App_HealthMonitor_SimSetThzLocked(uint8_t locked);
void App_HealthMonitor_SimSetThzQualityBad(uint8_t bad);
void App_HealthMonitor_SimSetGimbalError(uint8_t error);
void App_HealthMonitor_ResetSimulation(uint32_t now);

#endif
