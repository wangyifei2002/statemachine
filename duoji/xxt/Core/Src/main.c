/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

	
/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <string.h>
#include <stdio.h>
#include "app_console.h"
#include "app_fsm.h"
#include "app_health_monitor.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

UART_HandleTypeDef huart1;

/* USER CODE BEGIN PV */

#if 0 /* Legacy FSM retained for reference; active implementation is app_fsm.c. */

#define SLOT_PERIOD_MS              200U

#define SELF_CHECK_PASS_SLOTS       1U
#define MM_STABLE_SLOTS             3U
#define GIMBAL_READY_SLOTS          2U
#define CAPTURE_TIMEOUT_SLOTS       30U
#define TRACK_BAD_SLOTS             3U
#define RECOVER_STABLE_SLOTS        3U
#define NO_RECOVER_TIMEOUT_SLOTS    20U

typedef enum
{
    S_IDLE = 0,
    S_FAULT,

    S0_SELF_CHECK,
    S1_SEARCH,
    S2_COARSE_ALIGN,
    S3_CAPTURE,
    S4_TRACK,
    S5_FALLBACK
} fsm_state_t;


typedef enum
{
    EVT_NONE = 0,
    EVT_START,
    EVT_RESET,
    EVT_FAULT,

    EVT_SELF_OK,
    EVT_SELF_FAIL,

    EVT_MM_OK,
    EVT_GIMBAL_OK,
    EVT_THZ_LOCK,
    EVT_TIMEOUT,
    EVT_LOST,
    EVT_MM_RECOVER,
    EVT_NO_RECOVER
} fsm_event_t;


typedef struct
{
    uint8_t mm_online;
    uint8_t thz_online;
    uint8_t gimbal_online;

    uint8_t mm_target_valid;
    uint8_t gimbal_ready;
    uint8_t thz_locked;
    uint8_t thz_quality_bad;
} sim_input_t;

sim_input_t g_in = {0};

fsm_state_t g_state = S_IDLE;

uint8_t rx_byte;
char cmd_buf[64];
uint8_t cmd_idx = 0;
char tx_buf[128];

volatile uint32_t g_event_flags = 0;

uint32_t g_slot_count = 0;
uint32_t g_last_slot_tick = 0;
uint32_t g_state_enter_slot = 0;

uint32_t g_self_ok_cnt = 0;
uint32_t g_mm_valid_cnt = 0;
uint32_t g_gimbal_ready_cnt = 0;
uint32_t g_track_bad_cnt = 0;
uint32_t g_recover_cnt = 0;

uint8_t g_s0_link_change_pending = 0;
uint8_t g_s5_wait_qbad_clear = 0;

#endif

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MPU_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);
/* USER CODE BEGIN PFP */

#if 0 /* Legacy FSM API retained for reference. */

void uart_send_str(const char *str);
void uart_send_line(const char *str);
const char *state_to_str(fsm_state_t s);
const char *event_to_str(fsm_event_t e);
void fsm_set_state(fsm_state_t new_state);
void fsm_enter_fault(const char *reason);

void post_event(fsm_event_t evt);
uint8_t check_event(fsm_event_t evt);
void clear_event(fsm_event_t evt);
void fsm_process_events(void);

void fsm_handle_command(const char *cmd);
void print_help(void);
void uart_poll_command(void);

void print_inputs(void);
void reset_state_counters(void);
void slot_run_once(void);
void slot_poll(void);

void clear_reacquire_inputs(void);

#endif

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

#if 0 /* Legacy polling console and FSM retained for reference. */

void slot_run_once(void)
{
    g_slot_count++;

    switch (g_state)
    {
    case S_IDLE:
        break;

    case S_FAULT:
        break;

		case S0_SELF_CHECK:
		{
				if (g_in.mm_online && g_in.thz_online && g_in.gimbal_online)
				{
						g_self_ok_cnt++;

						snprintf(tx_buf, sizeof(tx_buf),
										 "[slot=%lu] S0 self check progress: %lu/%u",
										 (unsigned long)g_slot_count,
										 (unsigned long)g_self_ok_cnt,
										 SELF_CHECK_PASS_SLOTS);
						uart_send_line(tx_buf);

						if (g_self_ok_cnt >= SELF_CHECK_PASS_SLOTS)
						{
								post_event(EVT_SELF_OK);
						}
				}
				else
				{
						g_self_ok_cnt = 0;

						if (g_s0_link_change_pending)
						{
								snprintf(tx_buf, sizeof(tx_buf),
												 "[slot=%lu] S0 waiting links: mm=%d thz=%d gimbal=%d",
												 (unsigned long)g_slot_count,
												 g_in.mm_online,
												 g_in.thz_online,
												 g_in.gimbal_online);
								uart_send_line(tx_buf);

								g_s0_link_change_pending = 0;
						}
				}
				break;
		}
		
    case S1_SEARCH:
        if (g_in.mm_target_valid)
        {
            g_mm_valid_cnt++;

            snprintf(tx_buf, sizeof(tx_buf),
                     "[slot=%lu] S1 wait target stable: %lu/%u",
                     (unsigned long)g_slot_count,
                     (unsigned long)g_mm_valid_cnt,
                     MM_STABLE_SLOTS);
            uart_send_line(tx_buf);

            if (g_mm_valid_cnt >= MM_STABLE_SLOTS)
            {
                post_event(EVT_MM_OK);
            }
        }
        else
        {
            if (g_mm_valid_cnt > 0)
            {
                snprintf(tx_buf, sizeof(tx_buf),
                         "[slot=%lu] S1 target lost, counter cleared",
                         (unsigned long)g_slot_count);
                uart_send_line(tx_buf);
            }
            g_mm_valid_cnt = 0;
        }
        break;

    case S2_COARSE_ALIGN:
        if (g_in.gimbal_ready)
        {
            g_gimbal_ready_cnt++;

            snprintf(tx_buf, sizeof(tx_buf),
                     "[slot=%lu] S2 wait gimbal ready: %lu/%u",
                     (unsigned long)g_slot_count,
                     (unsigned long)g_gimbal_ready_cnt,
                     GIMBAL_READY_SLOTS);
            uart_send_line(tx_buf);

            if (g_gimbal_ready_cnt >= GIMBAL_READY_SLOTS)
            {
                post_event(EVT_GIMBAL_OK);
            }
        }
        else
        {
            if (g_gimbal_ready_cnt > 0)
            {
                snprintf(tx_buf, sizeof(tx_buf),
                         "[slot=%lu] S2 gimbal not ready, counter cleared",
                         (unsigned long)g_slot_count);
                uart_send_line(tx_buf);
            }
            g_gimbal_ready_cnt = 0;
        }
        break;

    case S3_CAPTURE:
    {
        uint32_t wait_slots = g_slot_count - g_state_enter_slot;

        if (g_in.thz_locked)
        {
            snprintf(tx_buf, sizeof(tx_buf),
                     "[slot=%lu] S3 capture success: thz_locked=1",
                     (unsigned long)g_slot_count);
            uart_send_line(tx_buf);

            post_event(EVT_THZ_LOCK);
        }
        else
        {
            snprintf(tx_buf, sizeof(tx_buf),
                     "[slot=%lu] S3 waiting lock: %lu/%u",
                     (unsigned long)g_slot_count,
                     (unsigned long)wait_slots,
                     CAPTURE_TIMEOUT_SLOTS);
            uart_send_line(tx_buf);

            if (wait_slots >= CAPTURE_TIMEOUT_SLOTS)
            {
                post_event(EVT_TIMEOUT);
            }
        }
        break;
    }

    case S4_TRACK:
        if (g_in.thz_quality_bad)
        {
            g_track_bad_cnt++;

            snprintf(tx_buf, sizeof(tx_buf),
                     "[slot=%lu] S4 bad quality count: %lu/%u",
                     (unsigned long)g_slot_count,
                     (unsigned long)g_track_bad_cnt,
                     TRACK_BAD_SLOTS);
            uart_send_line(tx_buf);

            if (g_track_bad_cnt >= TRACK_BAD_SLOTS)
            {
                post_event(EVT_LOST);
            }
        }
        else
        {
            if (g_track_bad_cnt > 0)
            {
                snprintf(tx_buf, sizeof(tx_buf),
                         "[slot=%lu] S4 quality recovered, counter cleared",
                         (unsigned long)g_slot_count);
                uart_send_line(tx_buf);
            }
            g_track_bad_cnt = 0;
        }
        break;

		case S5_FALLBACK:
		{
				uint32_t stay_slots = g_slot_count - g_state_enter_slot;

				if (g_s5_wait_qbad_clear)
				{
						if (g_in.thz_quality_bad)
						{
								if ((stay_slots % 5U) == 0U || stay_slots == 1U)
								{
										snprintf(tx_buf, sizeof(tx_buf),
														 "[slot=%lu] S5 waiting qbad_off: qbad=%d",
														 (unsigned long)g_slot_count,
														 g_in.thz_quality_bad);
										uart_send_line(tx_buf);
								}
						}
						else
						{
								g_s5_wait_qbad_clear = 0;
								g_state_enter_slot = g_slot_count;
								reset_state_counters();

								snprintf(tx_buf, sizeof(tx_buf),
												 "[slot=%lu] S5 qbad cleared, reacquire enabled",
												 (unsigned long)g_slot_count);
								uart_send_line(tx_buf);
						}

						break;
				}

				
				stay_slots = g_slot_count - g_state_enter_slot;

				if (g_in.mm_target_valid)
				{
						g_recover_cnt++;

						snprintf(tx_buf, sizeof(tx_buf),
										 "[slot=%lu] S5 wait recover stable: %lu/%u",
										 (unsigned long)g_slot_count,
										 (unsigned long)g_recover_cnt,
										 RECOVER_STABLE_SLOTS);
						uart_send_line(tx_buf);

						if (g_recover_cnt >= RECOVER_STABLE_SLOTS)
						{
								post_event(EVT_MM_RECOVER);
						}
				}
				else
				{
						if (g_recover_cnt > 0)
						{
								snprintf(tx_buf, sizeof(tx_buf),
												 "[slot=%lu] S5 recover interrupted, counter cleared",
												 (unsigned long)g_slot_count);
								uart_send_line(tx_buf);
						}

						g_recover_cnt = 0;

						if ((stay_slots % 5U) == 0U || stay_slots >= NO_RECOVER_TIMEOUT_SLOTS)
						{
								snprintf(tx_buf, sizeof(tx_buf),
												 "[slot=%lu] S5 waiting recover timeout: %lu/%u",
												 (unsigned long)g_slot_count,
												 (unsigned long)stay_slots,
												 NO_RECOVER_TIMEOUT_SLOTS);
								uart_send_line(tx_buf);
						}

						if (stay_slots >= NO_RECOVER_TIMEOUT_SLOTS)
						{
								post_event(EVT_NO_RECOVER);
						}
				}
				break;
		}

				
		default:
        post_event(EVT_FAULT);
        break;
    }
}


void slot_poll(void)
{
    uint32_t now = HAL_GetTick();

    while ((now - g_last_slot_tick) >= SLOT_PERIOD_MS)
    {
        g_last_slot_tick += SLOT_PERIOD_MS;
        slot_run_once();
    }
}

void uart_send_str(const char *str)
{
    HAL_UART_Transmit(&huart1, (uint8_t *)str, strlen(str), HAL_MAX_DELAY);
}

void uart_send_line(const char *str)
{
    HAL_UART_Transmit(&huart1, (uint8_t *)str, strlen(str), HAL_MAX_DELAY);
    HAL_UART_Transmit(&huart1, (uint8_t *)"\r\n", 2, HAL_MAX_DELAY);
}

void print_inputs(void)
{
    snprintf(tx_buf, sizeof(tx_buf),
             "IN: mm_link=%d thz_link=%d gimbal_link=%d target=%d gimbal_ready=%d thz_lock=%d qbad=%d",
             g_in.mm_online,
             g_in.thz_online,
             g_in.gimbal_online,
             g_in.mm_target_valid,
             g_in.gimbal_ready,
             g_in.thz_locked,
             g_in.thz_quality_bad);
    uart_send_line(tx_buf);
}

void reset_state_counters(void)
{
    g_self_ok_cnt = 0;
    g_mm_valid_cnt = 0;
    g_gimbal_ready_cnt = 0;
    g_track_bad_cnt = 0;
    g_recover_cnt = 0;
}

void clear_reacquire_inputs(void)
{
    g_in.mm_target_valid = 0;
    g_in.gimbal_ready = 0;
    g_in.thz_locked = 0;
}

const char *state_to_str(fsm_state_t s)
{
    switch (s)
    {
    case S_IDLE:            return "S_IDLE";
    case S_FAULT:           return "S_FAULT";
    case S0_SELF_CHECK:     return "S0_SELF_CHECK";
    case S1_SEARCH:         return "S1_SEARCH";
    case S2_COARSE_ALIGN:   return "S2_COARSE_ALIGN";
    case S3_CAPTURE:        return "S3_CAPTURE";
    case S4_TRACK:          return "S4_TRACK";
    case S5_FALLBACK:       return "S5_FALLBACK";
    default:                return "UNKNOWN";
    }
}

const char *event_to_str(fsm_event_t e)
{
    switch (e)
    {
    case EVT_START:       return "EVT_START";
    case EVT_RESET:       return "EVT_RESET";
    case EVT_FAULT:       return "EVT_FAULT";
    case EVT_SELF_OK:     return "EVT_SELF_OK";
    case EVT_SELF_FAIL:   return "EVT_SELF_FAIL";
    case EVT_MM_OK:       return "EVT_MM_OK";
    case EVT_GIMBAL_OK:   return "EVT_GIMBAL_OK";
    case EVT_THZ_LOCK:    return "EVT_THZ_LOCK";
    case EVT_TIMEOUT:     return "EVT_TIMEOUT";
    case EVT_LOST:        return "EVT_LOST";
    case EVT_MM_RECOVER:  return "EVT_MM_RECOVER";
    case EVT_NO_RECOVER:  return "EVT_NO_RECOVER";
    default:              return "EVT_NONE";
    }
}

void post_event(fsm_event_t evt)
{
    if (evt == EVT_NONE)
        return;

    if ((g_event_flags & (1UL << evt)) == 0)
    {
        g_event_flags |= (1UL << evt);

        snprintf(tx_buf, sizeof(tx_buf),
                 "[slot=%lu] EVENT + %s",
                 (unsigned long)g_slot_count,
                 event_to_str(evt));
        uart_send_line(tx_buf);
    }
}

uint8_t check_event(fsm_event_t evt)
{
    return (g_event_flags & (1UL << evt)) ? 1 : 0;
}

void clear_event(fsm_event_t evt)
{
    g_event_flags &= ~(1UL << evt);
}

void fsm_set_state(fsm_state_t new_state)
{
    fsm_state_t old_state = g_state;

    if (old_state == new_state)
    {
        return;
    }

    g_state = new_state;
    g_state_enter_slot = g_slot_count;
    reset_state_counters();

    if (g_state != S0_SELF_CHECK)
    {
        g_s0_link_change_pending = 0;
    }

    if (g_state == S5_FALLBACK)
    {
        clear_reacquire_inputs();
        g_s5_wait_qbad_clear = 1;
    }
    else
    {
        g_s5_wait_qbad_clear = 0;
    }

    if (g_slot_count == 0)
    {
        snprintf(tx_buf, sizeof(tx_buf),
                 "[slot=%lu] STATE -> %s",
                 (unsigned long)g_slot_count,
                 state_to_str(g_state));
    }
    else
    {
        snprintf(tx_buf, sizeof(tx_buf),
                 "[slot=%lu] STATE %s -> %s",
                 (unsigned long)g_slot_count,
                 state_to_str(old_state),
                 state_to_str(g_state));
    }

    uart_send_line(tx_buf);

    if (g_state == S5_FALLBACK)
    {
        uart_send_line("S5 entry: clear target/gimbal_ready/thz_lock, wait qbad_off");
    }
}


void fsm_enter_fault(const char *reason)
{
    snprintf(tx_buf, sizeof(tx_buf), "FAULT: %s", reason);
    uart_send_line(tx_buf);
    fsm_set_state(S_FAULT);
}

void print_help(void)
{
    uart_send_line("==== CMD LIST ====");
    uart_send_line("help              : show help");
    uart_send_line("status            : show state / slot / events / inputs");
    uart_send_line("inputs            : show current raw inputs");
    uart_send_line("start             : post EVT_START");
    uart_send_line("reset             : post EVT_RESET");
    uart_send_line("fault             : post EVT_FAULT");
  	uart_send_line("selffail          : post EVT_SELF_FAIL in S0");

    uart_send_line("mm_link_on/off    : set mm online flag");
    uart_send_line("thz_link_on/off   : set thz online flag");
    uart_send_line("gimbal_link_on/off: set gimbal online flag");

    uart_send_line("target_on/off     : set mm target valid");
    uart_send_line("gimbal_ready_on/off : set gimbal ready");
    uart_send_line("thz_lock_on/off   : set thz locked");
    uart_send_line("qbad_on/off       : set thz quality bad");
}


void fsm_handle_command(const char *cmd)
{
    if (strcmp(cmd, "help") == 0)
    {
        print_help();
        return;
    }

    if (strcmp(cmd, "status") == 0)
    {
        snprintf(tx_buf, sizeof(tx_buf), "CURRENT STATE = %s", state_to_str(g_state));
        uart_send_line(tx_buf);

        snprintf(tx_buf, sizeof(tx_buf), "EVENT FLAGS = 0x%08lX", (unsigned long)g_event_flags);
        uart_send_line(tx_buf);

        snprintf(tx_buf, sizeof(tx_buf), "SLOT COUNT = %lu", (unsigned long)g_slot_count);
        uart_send_line(tx_buf);

        print_inputs();
        return;
    }

    if (strcmp(cmd, "start") == 0)
    {
        post_event(EVT_START);
        return;
    }

    if (strcmp(cmd, "reset") == 0)
    {
        post_event(EVT_RESET);
        return;
    }

    if (strcmp(cmd, "fault") == 0)
    {
        post_event(EVT_FAULT);
        return;
    }

    if (strcmp(cmd, "inputs") == 0)
    {
        print_inputs();
        return;
    }

		if (strcmp(cmd, "mm_link_on") == 0)
		{
				if (g_in.mm_online != 1)
				{
						g_in.mm_online = 1;
						g_s0_link_change_pending = 1;
				}
				uart_send_line("SET: mm_online=1");
				return;
		}
		
		if (strcmp(cmd, "mm_link_off") == 0)
		{
				if (g_in.mm_online != 0)
				{
						g_in.mm_online = 0;
						g_s0_link_change_pending = 1;
				}
				uart_send_line("SET: mm_online=0");
				return;
		}

		if (strcmp(cmd, "thz_link_on") == 0)
		{
				if (g_in.thz_online != 1)
				{
						g_in.thz_online = 1;
						g_s0_link_change_pending = 1;
				}
				uart_send_line("SET: thz_online=1");
				return;
		}
		
		if (strcmp(cmd, "thz_link_off") == 0)
		{
				if (g_in.thz_online != 0)
				{
						g_in.thz_online = 0;
						g_s0_link_change_pending = 1;
				}
				uart_send_line("SET: thz_online=0");
				return;
		}

		if (strcmp(cmd, "gimbal_link_on") == 0)
		{
				if (g_in.gimbal_online != 1)
				{
						g_in.gimbal_online = 1;
						g_s0_link_change_pending = 1;
				}
				uart_send_line("SET: gimbal_online=1");
				return;
		}

		if (strcmp(cmd, "gimbal_link_off") == 0)
		{
				if (g_in.gimbal_online != 0)
				{
						g_in.gimbal_online = 0;
						g_s0_link_change_pending = 1;
				}
				uart_send_line("SET: gimbal_online=0");
				return;
		}

    if (strcmp(cmd, "target_on") == 0)
    {
        g_in.mm_target_valid = 1;
        uart_send_line("SET: mm_target_valid=1");
        return;
    }
    if (strcmp(cmd, "target_off") == 0)
    {
        g_in.mm_target_valid = 0;
        uart_send_line("SET: mm_target_valid=0");
        return;
    }

    if (strcmp(cmd, "gimbal_ready_on") == 0)
    {
        g_in.gimbal_ready = 1;
        uart_send_line("SET: gimbal_ready=1");
        return;
    }
    if (strcmp(cmd, "gimbal_ready_off") == 0)
    {
        g_in.gimbal_ready = 0;
        uart_send_line("SET: gimbal_ready=0");
        return;
    }

    if (strcmp(cmd, "thz_lock_on") == 0)
    {
        g_in.thz_locked = 1;
        uart_send_line("SET: thz_locked=1");
        return;
    }
    if (strcmp(cmd, "thz_lock_off") == 0)
    {
        g_in.thz_locked = 0;
        uart_send_line("SET: thz_locked=0");
        return;
    }

    if (strcmp(cmd, "qbad_on") == 0)
    {
        g_in.thz_quality_bad = 1;
        uart_send_line("SET: thz_quality_bad=1");
        return;
    }
    if (strcmp(cmd, "qbad_off") == 0)
    {
        g_in.thz_quality_bad = 0;
        uart_send_line("SET: thz_quality_bad=0");
        return;
    }

		if (strcmp(cmd, "selffail") == 0)
		{
				if (g_state == S0_SELF_CHECK)
				{
						post_event(EVT_SELF_FAIL);
				}
				else
				{
						uart_send_line("selffail only valid in S0_SELF_CHECK");
				}
				return;
		}

    uart_send_line("UNKNOWN CMD");
}


void fsm_process_events(void)
{
    if (check_event(EVT_RESET))
    {
        clear_event(EVT_RESET);
        g_event_flags = 0;
        fsm_set_state(S_IDLE);
        return;
    }

    if (check_event(EVT_FAULT))
    {
        clear_event(EVT_FAULT);
        g_event_flags = 0;
        fsm_enter_fault("manual fault");
        return;
    }

    switch (g_state)
    {
    case S_IDLE:
        if (check_event(EVT_START))
        {
            clear_event(EVT_START);
            fsm_set_state(S0_SELF_CHECK);
        }
        break;

    case S_FAULT:
        break;

		case S0_SELF_CHECK:
				if (check_event(EVT_SELF_FAIL))
				{
						clear_event(EVT_SELF_FAIL);
						g_event_flags = 0;
						fsm_enter_fault("self check failed");
				}
				else if (check_event(EVT_SELF_OK))
				{
						clear_event(EVT_SELF_OK);
						fsm_set_state(S1_SEARCH);
				}
				break;

    case S1_SEARCH:
        if (check_event(EVT_MM_OK))
        {
            clear_event(EVT_MM_OK);
            fsm_set_state(S2_COARSE_ALIGN);
        }
        break;

    case S2_COARSE_ALIGN:
        if (check_event(EVT_GIMBAL_OK))
        {
            clear_event(EVT_GIMBAL_OK);
            fsm_set_state(S3_CAPTURE);
        }
        break;

    case S3_CAPTURE:
        if (check_event(EVT_TIMEOUT))
        {
            clear_event(EVT_TIMEOUT);
            fsm_set_state(S5_FALLBACK);
        }
        else if (check_event(EVT_THZ_LOCK))
        {
            clear_event(EVT_THZ_LOCK);
            fsm_set_state(S4_TRACK);
        }
        break;

    case S4_TRACK:
        if (check_event(EVT_LOST))
        {
            clear_event(EVT_LOST);
            fsm_set_state(S5_FALLBACK);
        }
        break;

    case S5_FALLBACK:
        if (check_event(EVT_MM_RECOVER))
        {
            clear_event(EVT_MM_RECOVER);
            fsm_set_state(S2_COARSE_ALIGN);
        }
        else if (check_event(EVT_NO_RECOVER))
        {
            clear_event(EVT_NO_RECOVER);
            fsm_set_state(S1_SEARCH);
        }
        break;

    default:
        g_event_flags = 0;
        fsm_enter_fault("illegal state");
        break;
    }
}


void uart_poll_command(void)
{
    if (HAL_UART_Receive(&huart1, &rx_byte, 1, 10) == HAL_OK)
    {
        if (rx_byte == '\r' || rx_byte == '\n')
        {
            if (cmd_idx > 0)
            {
                cmd_buf[cmd_idx] = '\0';

                snprintf(tx_buf, sizeof(tx_buf), "CMD: %s", cmd_buf);
                uart_send_line(tx_buf);

                fsm_handle_command(cmd_buf);

                cmd_idx = 0;
                memset(cmd_buf, 0, sizeof(cmd_buf));
            }
        }
        else
        {
            if (cmd_idx < sizeof(cmd_buf) - 1)
            {
                cmd_buf[cmd_idx++] = (char)rx_byte;
            }
            else
            {
                cmd_idx = 0;
                memset(cmd_buf, 0, sizeof(cmd_buf));
                uart_send_line("CMD TOO LONG");
            }
        }
    }
}

#endif

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
	

int main(void)
{

  /* USER CODE BEGIN 1 */
	uint32_t now;

  /* USER CODE END 1 */

  /* MPU Configuration--------------------------------------------------------*/
  MPU_Config();

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
	
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART1_UART_Init();

  /* USER CODE BEGIN 2 */
	now = HAL_GetTick();
	App_HealthMonitor_Init(now, App_Fsm_PostHealthEvent);
	App_Console_Init(&huart1);
	App_Console_SendLine("");
	App_Console_SendLine("AIM FSM BOOT V2");
	App_Fsm_Init(now, App_Console_SendLine);
	App_Console_SendLine("Type help to see commands");

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
	
	while (1)
	{
			App_Console_Poll();
			now = HAL_GetTick();
			App_HealthMonitor_Run(now);
			App_Fsm_Run(now);
			App_Fsm_ProcessEvents(now);
	}
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Supply configuration update enable
  */
  HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);

  /** Configure the main internal regulator output voltage
  */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);

  while(!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_DIV1;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2
                              |RCC_CLOCKTYPE_D3PCLK1|RCC_CLOCKTYPE_D1PCLK1;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.SYSCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB3CLKDivider = RCC_APB3_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_APB1_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_APB2_DIV2;
  RCC_ClkInitStruct.APB4CLKDivider = RCC_APB4_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_1) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&huart1, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&huart1, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOA_CLK_ENABLE();

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

 /* MPU Configuration */

void MPU_Config(void)
{
  MPU_Region_InitTypeDef MPU_InitStruct = {0};

  /* Disables the MPU */
  HAL_MPU_Disable();

  /** Initializes and configures the Region and the memory to be protected
  */
  MPU_InitStruct.Enable = MPU_REGION_ENABLE;
  MPU_InitStruct.Number = MPU_REGION_NUMBER0;
  MPU_InitStruct.BaseAddress = 0x0;
  MPU_InitStruct.Size = MPU_REGION_SIZE_4GB;
  MPU_InitStruct.SubRegionDisable = 0x87;
  MPU_InitStruct.TypeExtField = MPU_TEX_LEVEL0;
  MPU_InitStruct.AccessPermission = MPU_REGION_NO_ACCESS;
  MPU_InitStruct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;
  MPU_InitStruct.IsShareable = MPU_ACCESS_SHAREABLE;
  MPU_InitStruct.IsCacheable = MPU_ACCESS_NOT_CACHEABLE;
  MPU_InitStruct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;

  HAL_MPU_ConfigRegion(&MPU_InitStruct);
  /* Enables the MPU */
  HAL_MPU_Enable(MPU_PRIVILEGED_DEFAULT);

}

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
