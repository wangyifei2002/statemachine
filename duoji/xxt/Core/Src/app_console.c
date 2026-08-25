#include "app_console.h"
#include "app_format.h"
#include "app_fsm.h"
#include "app_health_monitor.h"

#include <string.h>

#define CONSOLE_RX_RING_SIZE       128U
#define CONSOLE_TX_RING_SIZE       1024U
#define CONSOLE_CMD_SIZE           96U

typedef char console_ring_must_be_power_of_two[
    ((CONSOLE_RX_RING_SIZE & (CONSOLE_RX_RING_SIZE - 1U)) == 0U) ? 1 : -1];
typedef char console_tx_ring_must_be_power_of_two[
    ((CONSOLE_TX_RING_SIZE & (CONSOLE_TX_RING_SIZE - 1U)) == 0U) ? 1 : -1];

static UART_HandleTypeDef *g_console_uart;
static uint8_t g_irq_rx_byte;
static volatile uint16_t g_rx_head;
static volatile uint16_t g_rx_tail;
static volatile uint8_t g_rx_overflow;
static volatile uint8_t g_rx_error;
static uint8_t g_rx_ring[CONSOLE_RX_RING_SIZE];
static volatile uint16_t g_tx_head;
static volatile uint16_t g_tx_tail;
static volatile uint16_t g_tx_chunk_size;
static volatile uint8_t g_tx_busy;
static volatile uint8_t g_tx_overflow;
static volatile uint8_t g_tx_error;
static uint8_t g_tx_ring[CONSOLE_TX_RING_SIZE];
static char g_cmd_buffer[CONSOLE_CMD_SIZE];
static uint16_t g_cmd_index;

static uint8_t parse_signed_integer(const char **cursor, long *value)
{
    const char *text;
    long result = 0L;
    long sign = 1L;
    uint8_t have_digit = 0U;

    text = *cursor;
    while (*text == ' ')
    {
        text++;
    }
    if (*text == '-')
    {
        sign = -1L;
        text++;
    }
    else if (*text == '+')
    {
        text++;
    }

    while ((*text >= '0') && (*text <= '9'))
    {
        have_digit = 1U;
        result = (result * 10L) + (long)(*text - '0');
        text++;
    }

    if (!have_digit)
    {
        return 0U;
    }

    *value = result * sign;
    *cursor = text;
    return 1U;
}

static uint8_t parse_target_angle(const char *cmd,
                                  long *az_deg,
                                  long *el_deg)
{
    const char *cursor;

    if (strncmp(cmd, "target_angle ", 13U) != 0)
    {
        return 0U;
    }

    cursor = cmd + 13U;
    if (!parse_signed_integer(&cursor, az_deg) ||
        !parse_signed_integer(&cursor, el_deg))
    {
        return 0U;
    }

    while (*cursor == ' ')
    {
        cursor++;
    }
    return (*cursor == '\0') ? 1U : 0U;
}

static void print_help(void)
{
    App_Console_SendLine("==== CMD LIST ====");
    App_Console_SendLine("help | status | inputs");
    App_Console_SendLine("start | reset | sim_reset | fault | selffail");
    App_Console_SendLine("mm_link_on/off | bbu_link_on/off");
    App_Console_SendLine("thz_link_on/off | gimbal_link_on/off");
    App_Console_SendLine("bbu_ready_on/off | thz_ready_on/off");
    App_Console_SendLine("gimbal_module_ready_on/off");
    App_Console_SendLine("bbu_stale_on/off");
    App_Console_SendLine("target_on/off | target_angle <az> <el>");
    App_Console_SendLine("gimbal_ready_on/off | gimbal_error_on/off");
    App_Console_SendLine("thz_lock_on/off | qbad_on/off");
}

static void print_inputs(void)
{
    const app_device_snapshot_t *input;
    char text[192];

    input = App_HealthMonitor_GetSnapshot();
    App_Format(text, sizeof(text),
             "IN: BBU=%u/%u/fresh=%u target=%u angle=(%d,%d)",
             (unsigned int)input->bbu_online,
             (unsigned int)input->bbu_ready,
             (unsigned int)input->bbu_data_fresh,
             (unsigned int)input->mm_target_valid,
             input->target_az_deg, input->target_el_deg);
    App_Console_SendLine(text);

    App_Format(text, sizeof(text),
             "IN: THZ=%u/%u lock=%u qbad=%u GIMBAL=%u/%u ready=%u error=%u",
             (unsigned int)input->thz_online,
             (unsigned int)input->thz_ready,
             (unsigned int)input->thz_locked,
             (unsigned int)input->thz_quality_bad,
             (unsigned int)input->gimbal_online,
             (unsigned int)input->gimbal_module_ready,
             (unsigned int)input->gimbal_ready,
             (unsigned int)input->gimbal_error);
    App_Console_SendLine(text);
}

static void handle_command(const char *cmd)
{
    uint32_t now;
    long az_deg;
    long el_deg;

    now = HAL_GetTick();

    if (strcmp(cmd, "help") == 0)
    {
        print_help();
    }
    else if (strcmp(cmd, "status") == 0)
    {
        App_Fsm_PrintStatus();
    }
    else if (strcmp(cmd, "inputs") == 0)
    {
        print_inputs();
    }
    else if (strcmp(cmd, "start") == 0)
    {
        if (App_Fsm_GetState() == S_IDLE)
        {
            App_Fsm_PostEvent(EVT_START);
        }
        else
        {
            App_Console_SendLine("start only valid in S_IDLE");
        }
    }
    else if (strcmp(cmd, "reset") == 0)
    {
        App_Fsm_PostEvent(EVT_RESET);
    }
    else if (strcmp(cmd, "sim_reset") == 0)
    {
        App_Fsm_Reset(now, 1U);
        App_Console_SendLine("simulation inputs cleared");
    }
    else if (strcmp(cmd, "fault") == 0)
    {
        App_Fsm_PostEvent(EVT_FAULT);
    }
    else if (strcmp(cmd, "selffail") == 0)
    {
        if (App_Fsm_GetState() == S0_SELF_CHECK)
        {
            App_Fsm_PostEvent(EVT_SELF_FAIL);
        }
        else
        {
            App_Console_SendLine("selffail only valid in S0_SELF_CHECK");
        }
    }
    else if ((strcmp(cmd, "mm_link_on") == 0) ||
             (strcmp(cmd, "bbu_link_on") == 0))
    {
        App_HealthMonitor_SimSetLink(APP_MODULE_BBU, 1U, now);
        App_Console_SendLine("SET: BBU link/ready/data on");
    }
    else if ((strcmp(cmd, "mm_link_off") == 0) ||
             (strcmp(cmd, "bbu_link_off") == 0))
    {
        App_HealthMonitor_SimSetLink(APP_MODULE_BBU, 0U, now);
        App_Console_SendLine("SET: BBU responding=0");
    }
    else if (strcmp(cmd, "thz_link_on") == 0)
    {
        App_HealthMonitor_SimSetLink(APP_MODULE_THZ, 1U, now);
        App_Console_SendLine("SET: THZ responding=1, ready=1");
    }
    else if (strcmp(cmd, "thz_link_off") == 0)
    {
        App_HealthMonitor_SimSetLink(APP_MODULE_THZ, 0U, now);
        App_Console_SendLine("SET: THZ responding=0");
    }
    else if (strcmp(cmd, "gimbal_link_on") == 0)
    {
        App_HealthMonitor_SimSetLink(APP_MODULE_GIMBAL, 1U, now);
        App_Console_SendLine("SET: gimbal link/ready on");
    }
    else if (strcmp(cmd, "gimbal_link_off") == 0)
    {
        App_HealthMonitor_SimSetLink(APP_MODULE_GIMBAL, 0U, now);
        App_Console_SendLine("SET: gimbal responding=0");
    }
    else if (strcmp(cmd, "bbu_ready_on") == 0)
    {
        App_HealthMonitor_SimSetModuleReady(APP_MODULE_BBU, 1U);
        App_Console_SendLine("SET: BBU ready=1");
    }
    else if (strcmp(cmd, "bbu_ready_off") == 0)
    {
        App_HealthMonitor_SimSetModuleReady(APP_MODULE_BBU, 0U);
        App_Console_SendLine("SET: BBU ready=0");
    }
    else if (strcmp(cmd, "thz_ready_on") == 0)
    {
        App_HealthMonitor_SimSetModuleReady(APP_MODULE_THZ, 1U);
        App_Console_SendLine("SET: THZ ready=1");
    }
    else if (strcmp(cmd, "thz_ready_off") == 0)
    {
        App_HealthMonitor_SimSetModuleReady(APP_MODULE_THZ, 0U);
        App_Console_SendLine("SET: THZ ready=0");
    }
    else if (strcmp(cmd, "gimbal_module_ready_on") == 0)
    {
        App_HealthMonitor_SimSetModuleReady(APP_MODULE_GIMBAL, 1U);
        App_Console_SendLine("SET: gimbal module_ready=1");
    }
    else if (strcmp(cmd, "gimbal_module_ready_off") == 0)
    {
        App_HealthMonitor_SimSetModuleReady(APP_MODULE_GIMBAL, 0U);
        App_Console_SendLine("SET: gimbal module_ready=0");
    }
    else if (strcmp(cmd, "bbu_stale_on") == 0)
    {
        App_HealthMonitor_SimSetBbuDataStreaming(0U, now);
        App_Console_SendLine("SET: BBU target data stream stopped");
    }
    else if (strcmp(cmd, "bbu_stale_off") == 0)
    {
        App_HealthMonitor_SimSetBbuDataStreaming(1U, now);
        App_Console_SendLine("SET: BBU target data stream resumed");
    }
    else if (strcmp(cmd, "target_on") == 0)
    {
        App_HealthMonitor_SimSetTargetValid(1U);
        App_Console_SendLine("SET: BBU target_valid=1");
    }
    else if (strcmp(cmd, "target_off") == 0)
    {
        App_HealthMonitor_SimSetTargetValid(0U);
        App_Console_SendLine("SET: BBU target_valid=0");
    }
    else if (parse_target_angle(cmd, &az_deg, &el_deg))
    {
        if ((az_deg < -180L) || (az_deg > 180L) ||
            (el_deg < -90L) || (el_deg > 90L))
        {
            App_Console_SendLine("angle range: az +/-180, el +/-90");
        }
        else
        {
            App_HealthMonitor_SimSetTargetAngle((int16_t)az_deg,
                                                (int16_t)el_deg);
            App_Console_SendLine("SET: BBU target angle updated");
        }
    }
    else if (strcmp(cmd, "gimbal_ready_on") == 0)
    {
        App_HealthMonitor_SimSetGimbalReady(1U);
        App_Console_SendLine("SET: gimbal position ready=1");
    }
    else if (strcmp(cmd, "gimbal_ready_off") == 0)
    {
        App_HealthMonitor_SimSetGimbalReady(0U);
        App_Console_SendLine("SET: gimbal position ready=0");
    }
    else if (strcmp(cmd, "gimbal_error_on") == 0)
    {
        App_HealthMonitor_SimSetGimbalError(1U);
        App_Console_SendLine("SET: gimbal error=1");
    }
    else if (strcmp(cmd, "gimbal_error_off") == 0)
    {
        App_HealthMonitor_SimSetGimbalError(0U);
        App_Console_SendLine("SET: gimbal error=0");
    }
    else if (strcmp(cmd, "thz_lock_on") == 0)
    {
        App_HealthMonitor_SimSetThzLocked(1U);
        App_Console_SendLine("SET: THZ locked=1");
    }
    else if (strcmp(cmd, "thz_lock_off") == 0)
    {
        App_HealthMonitor_SimSetThzLocked(0U);
        App_Console_SendLine("SET: THZ locked=0");
    }
    else if (strcmp(cmd, "qbad_on") == 0)
    {
        App_HealthMonitor_SimSetThzQualityBad(1U);
        App_Console_SendLine("SET: THZ quality_bad=1");
    }
    else if (strcmp(cmd, "qbad_off") == 0)
    {
        App_HealthMonitor_SimSetThzQualityBad(0U);
        App_Console_SendLine("SET: THZ quality_bad=0");
    }
    else
    {
        App_Console_SendLine("UNKNOWN CMD (type help)");
    }
}

static uint8_t ring_pop(uint8_t *byte)
{
    if (g_rx_tail == g_rx_head)
    {
        return 0U;
    }

    *byte = g_rx_ring[g_rx_tail];
    g_rx_tail = (uint16_t)((g_rx_tail + 1U) &
                           (CONSOLE_RX_RING_SIZE - 1U));
    return 1U;
}

static void tx_start_locked(void)
{
    uint16_t size;

    if (g_tx_busy || (g_tx_tail == g_tx_head) ||
        (g_console_uart == 0))
    {
        return;
    }

    if (g_tx_head > g_tx_tail)
    {
        size = (uint16_t)(g_tx_head - g_tx_tail);
    }
    else
    {
        size = (uint16_t)(CONSOLE_TX_RING_SIZE - g_tx_tail);
    }

    g_tx_chunk_size = size;
    g_tx_busy = 1U;
    if (HAL_UART_Transmit_IT(g_console_uart,
                             &g_tx_ring[g_tx_tail],
                             size) != HAL_OK)
    {
        g_tx_busy = 0U;
        g_tx_error = 1U;
    }
}

static void tx_kick(void)
{
    uint32_t primask;

    primask = __get_PRIMASK();
    __disable_irq();
    tx_start_locked();
    if (!primask)
    {
        __enable_irq();
    }
}

void App_Console_Init(UART_HandleTypeDef *huart)
{
    g_console_uart = huart;
    g_rx_head = 0U;
    g_rx_tail = 0U;
    g_rx_overflow = 0U;
    g_rx_error = 0U;
    g_tx_head = 0U;
    g_tx_tail = 0U;
    g_tx_chunk_size = 0U;
    g_tx_busy = 0U;
    g_tx_overflow = 0U;
    g_tx_error = 0U;
    g_cmd_index = 0U;
    memset(g_cmd_buffer, 0, sizeof(g_cmd_buffer));
    HAL_UART_Receive_IT(g_console_uart, &g_irq_rx_byte, 1U);
}

void App_Console_SendLine(const char *text)
{
    uint16_t length;
    uint16_t used;
    uint16_t free_space;
    uint16_t i;
    uint32_t primask;

    if ((g_console_uart == 0) || (text == 0))
    {
        return;
    }

    length = (uint16_t)strlen(text);
    primask = __get_PRIMASK();
    __disable_irq();

    used = (uint16_t)((g_tx_head - g_tx_tail) &
                      (CONSOLE_TX_RING_SIZE - 1U));
    free_space = (uint16_t)((CONSOLE_TX_RING_SIZE - 1U) - used);
    if ((uint32_t)length + 2U > free_space)
    {
        g_tx_overflow = 1U;
    }
    else
    {
        for (i = 0U; i < length; i++)
        {
            g_tx_ring[g_tx_head] = (uint8_t)text[i];
            g_tx_head = (uint16_t)((g_tx_head + 1U) &
                                   (CONSOLE_TX_RING_SIZE - 1U));
        }
        g_tx_ring[g_tx_head] = '\r';
        g_tx_head = (uint16_t)((g_tx_head + 1U) &
                               (CONSOLE_TX_RING_SIZE - 1U));
        g_tx_ring[g_tx_head] = '\n';
        g_tx_head = (uint16_t)((g_tx_head + 1U) &
                               (CONSOLE_TX_RING_SIZE - 1U));
        tx_start_locked();
    }

    if (!primask)
    {
        __enable_irq();
    }
}

void App_Console_Poll(void)
{
    uint8_t byte;
    char echo[CONSOLE_CMD_SIZE + 8U];

    if (g_rx_overflow)
    {
        g_rx_overflow = 0U;
        App_Console_SendLine("UART RX RING OVERFLOW");
    }
    if (g_rx_error)
    {
        g_rx_error = 0U;
        App_Console_SendLine("UART RX ERROR, receiver restarted");
    }
    if (g_tx_overflow)
    {
        g_tx_overflow = 0U;
        App_Console_SendLine("UART TX RING OVERFLOW");
    }
    if (g_tx_error)
    {
        g_tx_error = 0U;
        App_Console_SendLine("UART TX ERROR, sender restarted");
    }

    tx_kick();

    while (ring_pop(&byte))
    {
        if ((byte == '\r') || (byte == '\n'))
        {
            if (g_cmd_index > 0U)
            {
                g_cmd_buffer[g_cmd_index] = '\0';
                App_Format(echo, sizeof(echo), "CMD: %s", g_cmd_buffer);
                App_Console_SendLine(echo);
                handle_command(g_cmd_buffer);
                g_cmd_index = 0U;
                memset(g_cmd_buffer, 0, sizeof(g_cmd_buffer));
            }
        }
        else if ((byte == 0x08U) || (byte == 0x7FU))
        {
            if (g_cmd_index > 0U)
            {
                g_cmd_index--;
            }
        }
        else if ((byte >= 0x20U) && (byte <= 0x7EU))
        {
            if (g_cmd_index < (CONSOLE_CMD_SIZE - 1U))
            {
                g_cmd_buffer[g_cmd_index++] = (char)byte;
            }
            else
            {
                g_cmd_index = 0U;
                memset(g_cmd_buffer, 0, sizeof(g_cmd_buffer));
                App_Console_SendLine("CMD TOO LONG");
            }
        }
    }
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    uint16_t next_head;

    if (huart != g_console_uart)
    {
        return;
    }

    next_head = (uint16_t)((g_rx_head + 1U) &
                           (CONSOLE_RX_RING_SIZE - 1U));
    if (next_head == g_rx_tail)
    {
        g_rx_overflow = 1U;
    }
    else
    {
        g_rx_ring[g_rx_head] = g_irq_rx_byte;
        g_rx_head = next_head;
    }

    HAL_UART_Receive_IT(g_console_uart, &g_irq_rx_byte, 1U);
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart != g_console_uart)
    {
        return;
    }

    g_tx_tail = (uint16_t)((g_tx_tail + g_tx_chunk_size) &
                           (CONSOLE_TX_RING_SIZE - 1U));
    g_tx_chunk_size = 0U;
    g_tx_busy = 0U;
    tx_start_locked();
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart != g_console_uart)
    {
        return;
    }

    g_rx_error = 1U;
    HAL_UART_AbortReceive(huart);
    HAL_UART_Receive_IT(g_console_uart, &g_irq_rx_byte, 1U);
}
