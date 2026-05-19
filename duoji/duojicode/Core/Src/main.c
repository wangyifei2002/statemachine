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
#include "i2c.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>      // 标准输入输出，用于 printf 重定向
#include <string.h>     // 字符串处理，用于 memcpy 等
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
// ========== 硬件配置参数 ==========
// PCF8574 I2C 地址 (7位地址为 0x20, 写操作时左移1位为 0x40)
#define PCF8574_ADDR           0x40
#define PCF8574_RS485_DIR_BIT  6U

// Pelco-D 协议固定帧头
#define PELCOD_SYNC_BYTE       0xFF

// 云台默认地址 (可根据实际设备修改)
#define PTZ_ADDR_DEFAULT       0x01

// 控制命令码定义
#define PELCOD_CMD_STOP        0x00    // 停止
#define PELCOD_CMD_PAN_LEFT    0x04    // 水平向左
#define PELCOD_CMD_PAN_RIGHT   0x02    // 水平向右
#define PELCOD_CMD_TILT_UP     0x08    // 垂直向上
#define PELCOD_CMD_TILT_DOWN   0x10    // 垂直向下

// RS485 半双工切换延时 (us) - 发送完毕后需等待TX完全关闭再切换到RX
#define RS485_TX_GAP_US        50

// 接收超时时间 (ms)
#define RX_TIMEOUT_MS           200
#define RX_BUFFER_SIZE          16U
#define RX_INTER_BYTE_TIMEOUT_MS 20U

// PB0 心跳灯闪烁间隔 (ms)，用于证明主循环未卡死
#define HEARTBEAT_INTERVAL_MS   500U

// 上电早期 LED 自检闪烁次数；如果要跳过自检，可改为 0
#define BOOT_LED_SELF_TEST_BLINKS 6U

// LED-only 板级点亮测试：1=只跑LED测试，不初始化I2C/USART/RS485
#define LED_ONLY_BRINGUP_TEST 0U

// USART1 板级串口测试：1=只跑LED+USART1测试，不初始化I2C/USART2/RS485
#define USART1_BRINGUP_TEST    0U

// USART1 原始串口发送测试：1=只用寄存器配置 PA9/USART1 TX，持续向电脑发送文本
#define USART1_RAW_TX_TEST     0U
#define USART1_RAW_BAUDRATE    115200U
#define USART1_RAW_CLOCK_HZ    HSI_VALUE

// RS485 + Pelco-D 云台闭环测试：1=raw USART1打印 + USART2/RS485控制云台，不使用LED
#define RS485_PELCOD_TEST      1U

// 软件 I2C 控制 PCF8574，避免当前阶段依赖 CubeMX I2C2 timing
#define PCF8574_SCL_GPIO_Port  GPIOH
#define PCF8574_SCL_Pin        GPIO_PIN_4
#define PCF8574_SDA_GPIO_Port  GPIOH
#define PCF8574_SDA_Pin        GPIO_PIN_5
#define SOFT_I2C_DELAY_US      5U
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN PV */
static uint8_t pcf8574_shadow = 0xFF;
static uint8_t pcf8574_last_ack = 0;
static uint32_t heartbeat_last_tick = 0;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
// ========== 用户业务函数声明 ==========
void Set_RS485_Direction(uint8_t to_transmit);
void PelcoD_Control_And_Query(uint8_t addr, uint8_t cmnd1, uint8_t cmnd2,
                              uint8_t data1, uint8_t data2, uint8_t *rx_buf,
                              uint8_t *rx_len, uint16_t timeout_ms);
static uint8_t PelcoD_CalcChecksum(const uint8_t *packet, uint8_t len);
static void PrintHexFrame(const char *prefix, const uint8_t *data, uint8_t len);
static void LED_Toggle_Once(void);
static void Heartbeat_Service(void);
static void Delay_With_Heartbeat(uint32_t delay_ms);
static void Board_LED_EarlySelfTest(void);
static void Board_LED_BringupLoop(void);
static void Board_USART1_BringupLoop(void);
static void Board_USART1_RawTxLoop(void);
static void Board_RS485_PelcoD_TestLoop(void);
static void USART1_RawInit_115200_HSI(void);
static void USART1_RawWriteChar(char ch);
static void USART1_RawWriteString(const char *s);
static void USART1_RawWriteUInt(uint32_t value);
static void Debug_WriteString(const char *s);
static void Debug_WriteUInt(uint32_t value);
static void Debug_WriteHexByte(uint8_t value);
static void PCF8574_SoftI2C_Init(void);
static uint8_t PCF8574_WriteByte(uint8_t data);
static void SoftI2C_SDA_Output(void);
static void SoftI2C_SDA_Input(void);
static void SoftI2C_SetSCL(uint8_t level);
static void SoftI2C_SetSDA(uint8_t level);
static void SoftI2C_Start(void);
static void SoftI2C_Stop(void);
static uint8_t SoftI2C_WriteByte(uint8_t data);
static void Board_DelayMs(uint32_t delay_ms);
static void DWT_Delay_Init(void);
static uint8_t PelcoD_ReceiveResponse(uint8_t *rx_buf, uint8_t max_len, uint16_t first_byte_timeout_ms);
void delay_us(uint32_t us);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/**
 * @brief  上电早期 LED 自检。
 * @note   该函数在 SystemClock_Config、I2C、USART 初始化之前运行。
 *         如果 DS1/PB0 在这里也不闪，优先排查固件启动、BOOT、LED硬件或板级跳线。
 */
static void Board_LED_EarlySelfTest(void)
{
#if (BOOT_LED_SELF_TEST_BLINKS > 0U)
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();

    GPIO_InitStruct.Pin = DS1_GREEN_Pin | DS0_RED_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    HAL_GPIO_WritePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(DS0_RED_GPIO_Port, DS0_RED_Pin, GPIO_PIN_SET);

    for (uint32_t i = 0; i < BOOT_LED_SELF_TEST_BLINKS; i++) {
        HAL_GPIO_TogglePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin);
        HAL_GPIO_TogglePin(DS0_RED_GPIO_Port, DS0_RED_Pin);
        HAL_Delay(250);
    }

    HAL_GPIO_WritePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(DS0_RED_GPIO_Port, DS0_RED_Pin, GPIO_PIN_SET);
#endif
}

/**
 * @brief  最小 LED 点亮/闪烁测试。
 * @note   用于板级排查：不进入 SystemClock_Config，不初始化 I2C/USART/RS485。
 *         如果这个循环里 DS1/PB0 仍不亮，问题基本在下载启动、LED管脚、跳线或硬件。
 */
static void Board_LED_BringupLoop(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();

    GPIO_InitStruct.Pin = DS1_GREEN_Pin | DS0_RED_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    while (1) {
        // 正点原子板载 DS0/DS1 按低电平点亮处理。
        HAL_GPIO_WritePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin, GPIO_PIN_RESET); // 绿灯亮
        HAL_GPIO_WritePin(DS0_RED_GPIO_Port, DS0_RED_Pin, GPIO_PIN_SET);       // 红灯灭
        HAL_Delay(500);

        HAL_GPIO_WritePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin, GPIO_PIN_SET);   // 绿灯灭
        HAL_GPIO_WritePin(DS0_RED_GPIO_Port, DS0_RED_Pin, GPIO_PIN_RESET);     // 红灯亮
        HAL_Delay(500);
    }
}

/**
 * @brief  LED + USART1 最小串口测试。
 * @note   只初始化 DS0/DS1 GPIO 和 USART1。
 *         刻意不调用 SystemClock_Config，避免外部 HSE/PLL 配置问题挡住 LED/串口排查。
 *         不初始化 I2C2、USART2、RS485，方便单独验证 USB_UART/P11/CH340/串口助手链路。
 */
static void Board_USART1_BringupLoop(void)
{
    const char *banner =
        "\r\n[UART TEST] USART1 bring-up started. Baud=115200, 8N1.\r\n"
        "[UART TEST] DS1/PB0 heartbeat toggles every 500ms.\r\n";
    uint32_t tick = 0;

    MX_GPIO_Init();

    for (uint32_t i = 0; i < 4U; i++) {
        HAL_GPIO_TogglePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin);
        HAL_Delay(125);
    }

    MX_USART1_UART_Init();

    HAL_UART_Transmit(&huart1, (uint8_t *)banner, strlen(banner), 200);
    printf("[printf] USART1 printf retarget OK.\r\n");

    while (1) {
        HAL_GPIO_TogglePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin);

        if ((tick & 1U) == 0U) {
            HAL_GPIO_WritePin(DS0_RED_GPIO_Port, DS0_RED_Pin, GPIO_PIN_SET);
        } else {
            HAL_GPIO_WritePin(DS0_RED_GPIO_Port, DS0_RED_Pin, GPIO_PIN_RESET);
        }

        printf("[UART TEST] tick=%lu, DS1/PB0 toggled, DS0/PB1=%s\r\n",
               (unsigned long)tick,
               ((tick & 1U) == 0U) ? "OFF" : "ON");

        tick++;
        HAL_Delay(500);
    }
}

/**
 * @brief  只用 USART1 TX 的最小串口输出测试。
 * @note   不初始化 LED、I2C、USART2、RS485，也不调用 SystemClock_Config。
 *         直接把 USART1 内核时钟切到 HSI，并把 PA9 配置为 USART1_TX。
 */
static void Board_USART1_RawTxLoop(void)
{
    uint32_t tick = 0;

    USART1_RawInit_115200_HSI();

    USART1_RawWriteString("\r\n[RAW USART1] PA9 TX only, 115200 8N1, clock=HSI.\r\n");
    USART1_RawWriteString("[RAW USART1] If you see this, USB-UART/P11/PA9 path is alive.\r\n");

    while (1) {
        USART1_RawWriteString("[RAW USART1] tick=");
        USART1_RawWriteUInt(tick++);
        USART1_RawWriteString("\r\n");
        HAL_Delay(500);
    }
}

/**
 * @brief  用寄存器直接初始化 USART1 TX。
 * @note   目标是排除 HAL UART、系统 PLL、其它外设初始化带来的干扰。
 */
static void USART1_RawInit_115200_HSI(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    /* 确保 HSI 和 HSI kernel clock 可用。复位后通常已经开启，这里再显式打开一次。 */
    SET_BIT(RCC->CR, RCC_CR_HSION | RCC_CR_HSIKERON);
    while ((RCC->CR & RCC_CR_HSIRDY) == 0U) {
        /* wait for HSI */
    }

#if defined(RCC_D2CCIP2R_USART16SEL) && defined(RCC_USART16CLKSOURCE_HSI)
    MODIFY_REG(RCC->D2CCIP2R, RCC_D2CCIP2R_USART16SEL, RCC_USART16CLKSOURCE_HSI);
#endif

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_USART1_CLK_ENABLE();

    GPIO_InitStruct.Pin = GPIO_PIN_9;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    CLEAR_BIT(USART1->CR1, USART_CR1_UE);

    USART1->CR1 = 0U;
    USART1->CR2 = 0U;
    USART1->CR3 = 0U;
    USART1->PRESC = 0U;
    USART1->BRR = (USART1_RAW_CLOCK_HZ + (USART1_RAW_BAUDRATE / 2U)) / USART1_RAW_BAUDRATE;
    USART1->CR1 = USART_CR1_TE;
    SET_BIT(USART1->CR1, USART_CR1_UE);
}

/**
 * @brief  USART1 轮询发送单个字符。
 */
static void USART1_RawWriteChar(char ch)
{
    while ((USART1->ISR & USART_ISR_TXE_TXFNF) == 0U) {
        /* wait for TX FIFO not full */
    }
    USART1->TDR = (uint8_t)ch;
}

/**
 * @brief  USART1 轮询发送字符串。
 */
static void USART1_RawWriteString(const char *s)
{
    while (s != NULL && *s != '\0') {
        USART1_RawWriteChar(*s++);
    }

    while ((USART1->ISR & USART_ISR_TC) == 0U) {
        /* wait for complete transmission */
    }
}

/**
 * @brief  USART1 轮询发送十进制无符号整数。
 */
static void USART1_RawWriteUInt(uint32_t value)
{
    char buf[10];
    uint32_t i = 0;

    if (value == 0U) {
        USART1_RawWriteChar('0');
        return;
    }

    while (value > 0U && i < sizeof(buf)) {
        buf[i++] = (char)('0' + (value % 10U));
        value /= 10U;
    }

    while (i > 0U) {
        USART1_RawWriteChar(buf[--i]);
    }
}

static void Debug_WriteString(const char *s)
{
    USART1_RawWriteString(s);
}

static void Debug_WriteUInt(uint32_t value)
{
    USART1_RawWriteUInt(value);
}

static void Debug_WriteHexByte(uint8_t value)
{
    static const char hex[] = "0123456789ABCDEF";

    USART1_RawWriteChar(hex[(value >> 4) & 0x0FU]);
    USART1_RawWriteChar(hex[value & 0x0FU]);
}

/**
 * @brief  RS485 + Pelco-D 云台闭环测试入口。
 * @note   该测试不使用 LED，不调用 SystemClock_Config，不初始化 I2C2 HAL。
 *         USART1 采用 raw TX 承载 printf，USART2 使用 HAL_UART_Transmit/Receive 控制云台。
 */
static void Board_RS485_PelcoD_TestLoop(void)
{
    uint8_t rx_buf[RX_BUFFER_SIZE];
    uint8_t rx_len = 0;

    USART1_RawInit_115200_HSI();
    Debug_WriteString("\r\n[BOOT] raw USART1 is alive before RS485 init.\r\n");
    DWT_Delay_Init();

    Debug_WriteString("========================================\r\n");
    Debug_WriteString("[SYSTEM] RS485 Pelco-D test start\r\n");
    Debug_WriteString("[SYSTEM] USART1: PA9 raw debug, 115200 8N1\r\n");
    Debug_WriteString("[SYSTEM] USART2: PA2/PA3 RS485, Pelco-D 9600 8N1\r\n");
    Debug_WriteString("========================================\r\n");

    PCF8574_SoftI2C_Init();
    Set_RS485_Direction(0);
    Debug_WriteString("[SYSTEM] PCF8574 dir init: ");
    Debug_WriteString(pcf8574_last_ack ? "ACK OK" : "ACK FAIL");
    Debug_WriteString(", default RX mode\r\n");

    Debug_WriteString("[SYSTEM] init USART2...\r\n");
    MX_USART2_UART_Init();
    Debug_WriteString("[SYSTEM] USART2 init done, start sequence\r\n\r\n");

    while (1) {
        Debug_WriteString("[STEP] pan left, speed=30, hold=3s\r\n");
        PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_PAN_LEFT,
                                 30, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
        Board_DelayMs(3000);

        Debug_WriteString("[STEP] stop, hold=2s\r\n");
        PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_STOP,
                                 0x00, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
        Board_DelayMs(2000);

        Debug_WriteString("[STEP] tilt up, speed=20, hold=3s\r\n");
        PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_TILT_UP,
                                 0x00, 20, rx_buf, &rx_len, RX_TIMEOUT_MS);
        Board_DelayMs(3000);

        Debug_WriteString("[STEP] stop, hold=2s\r\n");
        PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_STOP,
                                 0x00, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
        Board_DelayMs(2000);

        Debug_WriteString("\r\n[SYSTEM] one sequence done, restart after 1s\r\n\r\n");
        Board_DelayMs(1000);
    }
}

/**
 * @brief  初始化软件 I2C GPIO，用于控制 PCF8574。
 */
static void PCF8574_SoftI2C_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOH_CLK_ENABLE();

    GPIO_InitStruct.Pin = PCF8574_SCL_Pin | PCF8574_SDA_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_OD;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOH, &GPIO_InitStruct);

    SoftI2C_SetSCL(1);
    SoftI2C_SetSDA(1);
    delay_us(20);
}

/**
 * @brief  向 PCF8574 写 1 字节。
 * @return 1=地址和数据均收到 ACK，0=至少一次无 ACK。
 */
static uint8_t PCF8574_WriteByte(uint8_t data)
{
    uint8_t addr_ack;
    uint8_t data_ack;

    SoftI2C_Start();
    addr_ack = SoftI2C_WriteByte(PCF8574_ADDR);
    data_ack = SoftI2C_WriteByte(data);
    SoftI2C_Stop();

    return (uint8_t)(addr_ack && data_ack);
}

static void SoftI2C_SDA_Output(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    GPIO_InitStruct.Pin = PCF8574_SDA_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_OD;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(PCF8574_SDA_GPIO_Port, &GPIO_InitStruct);
}

static void SoftI2C_SDA_Input(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    GPIO_InitStruct.Pin = PCF8574_SDA_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(PCF8574_SDA_GPIO_Port, &GPIO_InitStruct);
}

static void SoftI2C_SetSCL(uint8_t level)
{
    HAL_GPIO_WritePin(PCF8574_SCL_GPIO_Port, PCF8574_SCL_Pin,
                      level ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static void SoftI2C_SetSDA(uint8_t level)
{
    HAL_GPIO_WritePin(PCF8574_SDA_GPIO_Port, PCF8574_SDA_Pin,
                      level ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static void SoftI2C_Start(void)
{
    SoftI2C_SDA_Output();
    SoftI2C_SetSDA(1);
    SoftI2C_SetSCL(1);
    delay_us(SOFT_I2C_DELAY_US);
    SoftI2C_SetSDA(0);
    delay_us(SOFT_I2C_DELAY_US);
    SoftI2C_SetSCL(0);
    delay_us(SOFT_I2C_DELAY_US);
}

static void SoftI2C_Stop(void)
{
    SoftI2C_SDA_Output();
    SoftI2C_SetSDA(0);
    SoftI2C_SetSCL(1);
    delay_us(SOFT_I2C_DELAY_US);
    SoftI2C_SetSDA(1);
    delay_us(SOFT_I2C_DELAY_US);
}

/**
 * @brief  软件 I2C 写 1 字节并读取 ACK。
 * @return 1=ACK，0=NACK。
 */
static uint8_t SoftI2C_WriteByte(uint8_t data)
{
    uint8_t ack;

    SoftI2C_SDA_Output();
    for (uint8_t mask = 0x80U; mask != 0U; mask >>= 1U) {
        SoftI2C_SetSDA((data & mask) ? 1U : 0U);
        delay_us(SOFT_I2C_DELAY_US);
        SoftI2C_SetSCL(1);
        delay_us(SOFT_I2C_DELAY_US);
        SoftI2C_SetSCL(0);
        delay_us(SOFT_I2C_DELAY_US);
    }

    SoftI2C_SetSDA(1);
    SoftI2C_SDA_Input();
    delay_us(SOFT_I2C_DELAY_US);
    SoftI2C_SetSCL(1);
    delay_us(SOFT_I2C_DELAY_US);
    ack = (HAL_GPIO_ReadPin(PCF8574_SDA_GPIO_Port, PCF8574_SDA_Pin) == GPIO_PIN_RESET) ? 1U : 0U;
    SoftI2C_SetSCL(0);
    delay_us(SOFT_I2C_DELAY_US);
    SoftI2C_SDA_Output();

    return ack;
}

/**
 * @brief  板级延时封装，当前测试阶段不驱动 LED。
 */
static void Board_DelayMs(uint32_t delay_ms)
{
    HAL_Delay(delay_ms);
}

/**
 * @brief  通过 PCF8574 的 P6 引脚控制 RS485 收发方向
 * @param  to_transmit: 1=发送模式(高电平使能发送驱动器), 0=接收模式(低电平使能接收器)
 * @note   使用 pcf8574_shadow 保留其它扩展口位，避免切换485方向时误改其它引脚。
 */
void Set_RS485_Direction(uint8_t to_transmit)
{
    if (to_transmit) {
        // 发送模式：P6 置高
        pcf8574_shadow |= (uint8_t)(1U << PCF8574_RS485_DIR_BIT);
    } else {
        // 接收模式：P6 置低
        pcf8574_shadow &= (uint8_t)~(1U << PCF8574_RS485_DIR_BIT);
    }

    // 当前 bring-up 阶段使用 PH4/PH5 软件 I2C，避免依赖 CubeMX I2C timing。
    // 注意：方向切换函数内不打印，避免发送结束后切回接收被 printf 拖慢。
    pcf8574_last_ack = PCF8574_WriteByte(pcf8574_shadow);
}

/**
 * @brief  计算 Pelco-D 协议校验和 (简单累加和，截断低8位)
 * @param  packet: 原始数据帧 (从地址字节开始，不包含 0xFF 同步头)
 * @param  len:   数据长度 (不含同步头，通常为6)
 * @return 校验和字节
 */
static uint8_t PelcoD_CalcChecksum(const uint8_t *packet, uint8_t len)
{
    uint8_t sum = 0;
    for (uint8_t i = 0; i < len; i++) {
        sum += packet[i];
    }
    return sum & 0xFF;
}

/**
 * @brief  打印十六进制数据帧 (格式化输出，方便调试观察)
 * @param  prefix: 前缀字符串，如 "[TX]" 或 "[RX]"
 * @param  data:   数据指针
 * @param  len:    数据长度
 */
static void PrintHexFrame(const char *prefix, const uint8_t *data, uint8_t len)
{
    Debug_WriteString(prefix);
    Debug_WriteString(" ");
    for (uint8_t i = 0; i < len; i++) {
        Debug_WriteHexByte(data[i]);
        Debug_WriteString(" ");
    }
    Debug_WriteString("\r\n");
}

/**
 * @brief  翻转 PB1 红灯，用于指示测试动作发生切换。
 * @note   PB0 独立作为 500ms 心跳灯，不再由动作切换函数控制。
 */
static void LED_Toggle_Once(void)
{
    HAL_GPIO_TogglePin(DS0_RED_GPIO_Port, DS0_RED_Pin);
}

/**
 * @brief  PB0 绿灯 500ms 心跳服务。
 * @note   需要在主循环和长延时中周期性调用；使用 HAL_GetTick，可自然处理计数回绕。
 */
static void Heartbeat_Service(void)
{
    uint32_t now = HAL_GetTick();

    if ((uint32_t)(now - heartbeat_last_tick) >= HEARTBEAT_INTERVAL_MS) {
        heartbeat_last_tick = now;
        HAL_GPIO_TogglePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin);
    }
}

/**
 * @brief  带心跳服务的阻塞延时。
 * @param  delay_ms: 延时时间，单位 ms。
 * @note   替代直接 HAL_Delay(3000/2000)，避免长延时期间 PB0 心跳停止。
 */
static void Delay_With_Heartbeat(uint32_t delay_ms)
{
    uint32_t start = HAL_GetTick();

    while ((uint32_t)(HAL_GetTick() - start) < delay_ms) {
        Heartbeat_Service();
        HAL_Delay(10);
    }
}

/**
 * @brief  使用 HAL_UART_Receive 带超时读取一帧可能长度不固定的云台回传。
 * @note   第一字节使用业务超时，后续字节使用较短字节间超时。
 *         这样不会固定等待16字节，也不会把 Pelco-D 帧头 0xFF 误判为结束符。
 */
static uint8_t PelcoD_ReceiveResponse(uint8_t *rx_buf, uint8_t max_len, uint16_t first_byte_timeout_ms)
{
    uint8_t len = 0;

    if (rx_buf == NULL || max_len == 0U) {
        return 0;
    }

    while (len < max_len) {
        uint16_t timeout = (len == 0U) ? first_byte_timeout_ms : RX_INTER_BYTE_TIMEOUT_MS;
        if (HAL_UART_Receive(&huart2, &rx_buf[len], 1, timeout) != HAL_OK) {
            break;
        }
        len++;
    }

    return len;
}

/**
 * @brief  完整的 Pelco-D 半双工闭环控制+查询函数
 *
 * 该函数执行以下步骤：
 *   1. 组装7字节标准 Pelco-D 指令帧 (同步头+地址+命令1+命令2+数据1+数据2+校验和)
 *   2. 切换 RS485 为发送模式
 *   3. 通过 USART2 阻塞发送7字节
 *   4. 延时极短时间确保最后一个bit离开发送器
 *   5. 立即切换 RS485 为接收模式
 *   6. 调用 HAL_UART_Receive 带超时等待云台回传
 *   7. 根据结果打印发送提示、回传数据或超时提示
 *
 * @param  addr:      云台设备地址 (默认0x01)
 * @param  cmnd1:    命令字节1 (通常为0x00或与镜物选择有关)
 * @param  cmnd2:    命令字节2 (控制方向：0x04=左转，0x08=上转，0x00=停止 等)
 * @param  data1:    数据字节1 (水平速度，0x01~0x3F，0x00=停止)
 * @param  data2:    数据字节2 (垂直速度，0x01~0x3F，0x00=停止)
 * @param  rx_buf:   接收缓存指针，用于输出回传数据
 * @param  rx_len:   接收到的数据长度指针，用于输出实际接收字节数
 * @param  timeout_ms: 接收超时时间 (毫秒)
 */
void PelcoD_Control_And_Query(uint8_t addr, uint8_t cmnd1, uint8_t cmnd2,
                              uint8_t data1, uint8_t data2, uint8_t *rx_buf,
                              uint8_t *rx_len, uint16_t timeout_ms)
{
    uint8_t tx_packet[7];
    uint8_t rx_temp[RX_BUFFER_SIZE] = {0};
    uint8_t actual_len = 0;

    if (rx_len != NULL) {
        *rx_len = 0;
    }

    // ========== Step 1: 组装 Pelco-D 指令帧 ==========
    tx_packet[0] = PELCOD_SYNC_BYTE;     // 同步头固定 0xFF
    tx_packet[1] = addr;                  // 设备地址
    tx_packet[2] = cmnd1;                 // 命令1
    tx_packet[3] = cmnd2;                 // 命令2
    tx_packet[4] = data1;                 // 数据1 (水平速度)
    tx_packet[5] = data2;                 // 数据2 (垂直速度)
    // 校验和 = 地址 + 命令1 + 命令2 + 数据1 + 数据2 的低8位累加和
    tx_packet[6] = PelcoD_CalcChecksum(&tx_packet[1], 5);

    // ========== Step 2: 切换 RS485 为发送模式 ==========
    Set_RS485_Direction(1);  // P6=1，发送驱动器使能

    // ========== Step 3: 阻塞发送7字节指令 ==========
    HAL_StatusTypeDef tx_ret = HAL_UART_Transmit(&huart2, tx_packet, 7, 100);

    // ========== Step 4: 极短延时确保最后一bit已从TX线移出 ==========
    // USART2 为 9600bps，HAL_UART_Transmit 返回前通常已等待 TC；
    // 这里保留一个很短的保护间隔，再立即切回接收。
    // 延时后必须立即切回接收，切方向绝不能被任何打印拖慢！
    delay_us(RS485_TX_GAP_US);

    // ========== Step 5: 立即切换 RS485 为接收模式 ==========
    Set_RS485_Direction(0);  // P6=0，接收器使能，发送驱动器禁用

    // ========== Step 6: 等待接收云台回传 (在切换到RX后立即开始) ==========
    memset(rx_temp, 0, sizeof(rx_temp));
    if (tx_ret == HAL_OK) {
        actual_len = PelcoD_ReceiveResponse(rx_temp, RX_BUFFER_SIZE, timeout_ms);
    }

    // ========== Step 7: 接收完成后才打印提示 (避免拖慢485方向切换和接收起始时刻) ==========
    if (tx_ret != HAL_OK) {
        Debug_WriteString("[PC] USART2 transmit failed, HAL status=");
        Debug_WriteUInt((uint32_t)tx_ret);
        Debug_WriteString("\r\n");
        PrintHexFrame("[TX]", tx_packet, 7);
        return;
    }

    Debug_WriteString("[PC] sent command: ");
    if (cmnd2 == PELCOD_CMD_PAN_LEFT && data1 > 0) {
        Debug_WriteString("pan left, speed=");
        Debug_WriteUInt(data1);
        Debug_WriteString("\r\n");
    } else if (cmnd2 == PELCOD_CMD_PAN_RIGHT && data1 > 0) {
        Debug_WriteString("pan right, speed=");
        Debug_WriteUInt(data1);
        Debug_WriteString("\r\n");
    } else if (cmnd2 == PELCOD_CMD_TILT_UP && data2 > 0) {
        Debug_WriteString("tilt up, speed=");
        Debug_WriteUInt(data2);
        Debug_WriteString("\r\n");
    } else if (cmnd2 == PELCOD_CMD_TILT_DOWN && data2 > 0) {
        Debug_WriteString("tilt down, speed=");
        Debug_WriteUInt(data2);
        Debug_WriteString("\r\n");
    } else {
        Debug_WriteString("stop\r\n");
    }
    PrintHexFrame("[TX]", tx_packet, 7);

    if (actual_len > 0U) {
        if (rx_buf != NULL && rx_len != NULL) {
            memcpy(rx_buf, rx_temp, actual_len);
            *rx_len = actual_len;
        }
        Debug_WriteString("[PC] received response, len=");
        Debug_WriteUInt(actual_len);
        Debug_WriteString("\r\n");
        PrintHexFrame("[RX]", rx_temp, actual_len);
    } else {
        Debug_WriteString("[PC] response timeout, wait_ms=");
        Debug_WriteUInt(timeout_ms);
        Debug_WriteString("\r\n");
    }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{
  /* USER CODE BEGIN 1 */
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */
#if (RS485_PELCOD_TEST == 1U)
  Board_RS485_PelcoD_TestLoop();
#endif
#if (USART1_RAW_TX_TEST == 1U)
  Board_USART1_RawTxLoop();
#endif
#if (USART1_BRINGUP_TEST == 1U)
  Board_USART1_BringupLoop();
#endif
#if (LED_ONLY_BRINGUP_TEST == 1U)
  Board_LED_BringupLoop();
#endif
  Board_LED_EarlySelfTest();

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_I2C2_Init();
  MX_USART2_UART_Init();
  MX_USART1_UART_Init();

  /* USER CODE BEGIN 2 */
  // ========== 系统初始化 ==========

  // 1. 初始化 DWT 计数器，为 RS485 收发切换提供微秒级保护延时
  DWT_Delay_Init();

  // 2. 默认将 RS485 设为接收模式，确保上电后不会导致总线冲突
  Set_RS485_Direction(0);

  // 3. 初始化指示灯状态：PB0心跳灯关闭，PB1动作指示灯关闭 (低电平点亮)
  // DS1_GREEN/DS0_RED 已在 MX_GPIO_Init() 中配置为推挽输出。
  HAL_GPIO_WritePin(DS1_GREEN_GPIO_Port, DS1_GREEN_Pin, GPIO_PIN_SET);   // 绿灯灭
  HAL_GPIO_WritePin(DS0_RED_GPIO_Port, DS0_RED_Pin, GPIO_PIN_SET);       // 红灯灭
  heartbeat_last_tick = HAL_GetTick();

  // 打印系统启动信息到 USART1，波特率115200，可在电脑串口助手查看
  printf("\r\n========================================\r\n");
  printf("  STM32H743 云台控制程序启动\r\n");
  printf("  主频: 400MHz  USART1: 115200bps\r\n");
  printf("  PCF8574@0x40 控制 RS485 方向\r\n");
  printf("========================================\r\n\r\n");

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    // ========== 工业云台自动化测试序列 (半双工闭环) ==========
    //
    // 测试流程：
    //   动作1: 云台左转(速度0x1E=30) → 保持3秒 → PB1动作指示翻转
    //   动作2: 云台停止 → 保持2秒   → PB1动作指示翻转
    //   动作3: 云台仰头(速度0x14=20) → 保持3秒 → PB1动作指示翻转
    //   动作4: 云台停止 → 保持2秒   → PB1动作指示翻转
    //   PB0绿灯在整个主循环中保持500ms心跳闪烁，用于证明程序正常运行
    // 循环往复，每步均通过 PelcoD_Control_And_Query 发送指令并接收云台反馈

    uint8_t rx_buf[16];
    uint8_t rx_len = 0;

    Heartbeat_Service();

    // ----- 动作1: 左转 (命令码0x04, 水平速度30) -----
    printf("[系统] === 动作1: 云台左转(速度30) ===\r\n");
    LED_Toggle_Once();
    PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_PAN_LEFT,
                             30, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
    Delay_With_Heartbeat(3000);  // 保持左转3秒，期间云台持续执行

    // ----- 动作2: 停止 -----
    printf("[系统] === 动作2: 云台停止 ===\r\n");
    LED_Toggle_Once();
    PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_STOP,
                             0x00, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
    Delay_With_Heartbeat(2000);  // 停止保持2秒

    // ----- 动作3: 仰头 (命令码0x08, 垂直速度20) -----
    printf("[系统] === 动作3: 云台仰头(速度20) ===\r\n");
    LED_Toggle_Once();
    PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_TILT_UP,
                             0x00, 20, rx_buf, &rx_len, RX_TIMEOUT_MS);
    Delay_With_Heartbeat(3000);  // 保持仰头3秒

    // ----- 动作4: 停止 -----
    printf("[系统] === 动作4: 云台停止 ===\r\n");
    LED_Toggle_Once();
    PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_STOP,
                             0x00, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
    Delay_With_Heartbeat(2000);  // 停止保持2秒

    // 一个完整测试周期结束后，打印分隔线，便于观察电脑端串口输出
    printf("\r\n[系统] ---- 一个测试周期完成，休息1秒后开始下一周期 ----\r\n\r\n");
    Delay_With_Heartbeat(1000);

    /* USER CODE END 3 */
  }
  /* USER CODE END WHILE */
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
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  while(!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 5;
  RCC_OscInitStruct.PLL.PLLN = 160;
  RCC_OscInitStruct.PLL.PLLP = 2;
  RCC_OscInitStruct.PLL.PLLQ = 2;
  RCC_OscInitStruct.PLL.PLLR = 2;
  RCC_OscInitStruct.PLL.PLLRGE = RCC_PLL1VCIRANGE_2;
  RCC_OscInitStruct.PLL.PLLVCOSEL = RCC_PLL1VCOWIDE;
  RCC_OscInitStruct.PLL.PLLFRACN = 0;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2
                              |RCC_CLOCKTYPE_D3PCLK1|RCC_CLOCKTYPE_D1PCLK1;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.SYSCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_APB1_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_APB2_DIV2;
  RCC_ClkInitStruct.APB4CLKDivider = RCC_APB4_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */

/**
 * @brief  初始化 Cortex-M7 DWT 周期计数器。
 * @note   delay_us() 依赖 CYCCNT。如果不显式打开，部分调试/启动环境下计数器可能不走。
 */
static void DWT_Delay_Init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

/**
 * @brief  微秒级延时函数 (使用 DWT Cycle Count 实现高精度延时)
 * @param  us: 延时微秒数
 * @note   在 USER CODE 2 中调用 DWT_Delay_Init() 后使用。
 */
void delay_us(uint32_t us)
{
    if ((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) == 0U) {
        DWT_Delay_Init();
    }

    uint32_t cycles = us * (SystemCoreClock / 1000000U);
    uint32_t start = DWT->CYCCNT;
    while ((DWT->CYCCNT - start) < cycles) {
        // 空循环等待
    }
}

/**
 * @brief  重定向 printf 到 USART1
 * @note   同时提供 fputc 和 __io_putchar，兼容 Keil MicroLIB / 标准库 / GCC 风格 retarget。
 */
static int Debug_PutChar(int ch)
{
#if (RS485_PELCOD_TEST == 1U) || (USART1_RAW_TX_TEST == 1U)
    USART1_RawWriteChar((char)ch);
#else
    HAL_UART_Transmit(&huart1, (uint8_t *)&ch, 1, 10);
#endif
    return ch;
}

int fputc(int ch, FILE *f)
{
    (void)f;
    return Debug_PutChar(ch);
}

int __io_putchar(int ch)
{
    return Debug_PutChar(ch);
}

#if !defined(__MICROLIB)
// 实现标准库需要的 stub 函数，替代半主机实现
struct __FILE { int handle; };
__attribute__((weak)) int _sys_open(const char *name, int openmode) { (void)name; (void)openmode; return -1; }
__attribute__((weak)) int _sys_close(int fh) { (void)fh; return 0; }
__attribute__((weak)) int _sys_read(int fh, unsigned char *buf, int len) { (void)fh; (void)buf; (void)len; return -1; }
__attribute__((weak)) int _sys_write(int fh, const unsigned char *buf, int len) { (void)fh; (void)buf; (void)len; return -1; }
__attribute__((weak)) int _sys_seek(int fh, long pos) { (void)fh; (void)pos; return -1; }
__attribute__((weak)) long _sys_flen(int fh) { (void)fh; return 0; }
__attribute__((weak)) int _sys_istty(int fh) { (void)fh; return 0; }
__attribute__((weak)) void _ttywrch(int ch) { (void)ch; }
__attribute__((weak)) void _sys_exit(int x) { (void)x; while(1); }
#endif

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
#if (RS485_PELCOD_TEST == 1U) || (USART1_RAW_TX_TEST == 1U)
  USART1_RawInit_115200_HSI();
  Debug_WriteString("\r\n[ERROR] Error_Handler entered.\r\n");
#endif
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}

#ifdef  USE_FULL_ASSERT
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
  /* User can add his own implementation to report the HAL error name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
/* EOF */
