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

// LED 闪烁间隔 (ms)
#define LED_TOGGLE_INTERVAL_MS  100
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/* USER CODE END PD */

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
void delay_us(uint32_t us);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/**
 * @brief  通过 PCF8574 的 P6 引脚控制 RS485 收发方向
 * @param  to_transmit: 1=发送模式(高电平使能发送驱动器), 0=接收模式(低电平使能接收器)
 * @note   PCF8574 每个引脚默认配置为高电平输出(开漏)，所以写入时需保持其他位不变
 */
void Set_RS485_Direction(uint8_t to_transmit)
{
    uint8_t pcf8574_data = 0xFF; // 默认所有引脚为高，保留其他位状态

    if (to_transmit) {
        // 发送模式：P6 置高
        pcf8574_data |= (1 << 6);
    } else {
        // 接收模式：P6 置低
        pcf8574_data &= ~(1 << 6);
    }

    // 通过 I2C2 写 PCF8574 (PH4=SCL, PH5=SDA 由 CubeMX 配置)
    // 超时100ms足够，PCF8574是低速扩展芯片
    HAL_I2C_Master_Transmit(&hi2c2, PCF8574_ADDR, &pcf8574_data, 1, 100);
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
    // 使用 printf 经 USART1 输出到电脑
    printf("%s ", prefix);
    for (uint8_t i = 0; i < len; i++) {
        printf("%02X ", data[i]);
    }
    printf("\r\n");
}

/**
 * @brief  翻转 PB0 和 PB1 的电平状态 (实现绿色/红色 LED 闪烁指示)
 * @note   每次调用时两个灯状态同时翻转，用于指示动作切换时刻
 */
static void LED_Toggle_Once(void)
{
    HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_0);  // 绿灯
    HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_1);  // 红灯
}

/**
 * @brief  完整的 Pelco-D 半双工闭环控制+查询函数
 *
 * 该函数执行以下步骤：
 *   1. 组装7字节标准 Pelco-D 指令帧 (同步头+地址+命令1+命令2+数据1+数据2+校验和)
 *   2. 切换 RS485 为发送模式
 *   3. 通过 USART2 阻塞发送7字节
 *   4. 打印发送提示到 USART1 (电脑端可见)
 *   5. 延时极短时间确保发送完成
 *   6. 立即切换 RS485 为接收模式
 *   7. 调用 HAL_UART_Receive 带超时等待云台回传
 *   8. 根据结果打印回传数据或超时提示
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
    uint8_t rx_temp[16] = {0};

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
    HAL_UART_Transmit(&huart2, tx_packet, 7, 100);

    // ========== Step 4: 极短延时确保最后一bit已从TX线移出 ==========
    // 对于 115200 波特率，1bit ≈ 8.68us，7字节≈70us
    // 延时后必须立即切回接收，切方向绝不能被任何打印拖慢！
    delay_us(RS485_TX_GAP_US);

    // ========== Step 5: 立即切换 RS485 为接收模式 ==========
    Set_RS485_Direction(0);  // P6=0，接收器使能，发送驱动器禁用

    // ========== Step 6: 等待接收云台回传 (在切换到RX后立即开始) ==========
    memset(rx_temp, 0, sizeof(rx_temp));
    HAL_StatusTypeDef ret = HAL_UART_Receive(&huart2, rx_temp, 16, timeout_ms);

    // ========== Step 7: 接收完成后才打印提示 (避免拖慢485方向切换) ==========
    if (ret == HAL_OK) {
        uint8_t actual_len = 0;
        for (int i = 0; i < 16; i++) {
            if (rx_temp[i] == 0xFF || rx_temp[i] == 0x0D) {
                actual_len = i + 1;
                break;
            }
            if (i == 15) actual_len = 16;
        }
        memcpy(rx_buf, rx_temp, actual_len);
        *rx_len = actual_len;
        printf("[电脑提示] -> 收到云台回传 (%d 字节):\r\n", actual_len);
        PrintHexFrame("[RX帧]", rx_buf, actual_len);
    } else {
        *rx_len = 0;
        printf("[电脑提示] -> 读取云台回传超时 (等待 %d ms)\r\n", timeout_ms);
    }

    // ========== Step 8: 打印本次发送的动作描述 (接收完成后打印，不影响时序) ==========
    printf("[电脑提示] -> 成功发送控制命令: ");
    if (cmnd2 == PELCOD_CMD_PAN_LEFT && data1 > 0) {
        printf("云台左转(速度%d)\r\n", data1);
    } else if (cmnd2 == PELCOD_CMD_PAN_RIGHT && data1 > 0) {
        printf("云台右转(速度%d)\r\n", data1);
    } else if (cmnd2 == PELCOD_CMD_TILT_UP && data2 > 0) {
        printf("云台仰头(速度%d)\r\n", data2);
    } else if (cmnd2 == PELCOD_CMD_TILT_DOWN && data2 > 0) {
        printf("云台低头(速度%d)\r\n", data2);
    } else {
        printf("云台停止\r\n");
    }
    PrintHexFrame("[TX帧]", tx_packet, 7);
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

  // 1. 使能 GPIOB 时钟 (PB0/PB1 用于 LED)
  __HAL_RCC_GPIOB_CLK_ENABLE();

  // 2. 配置 PB0/PB1 为推挽输出模式 (绿灯=PB0, 红灯=PB1)
  GPIO_InitTypeDef led_init = {0};
  led_init.Pin   = GPIO_PIN_0 | GPIO_PIN_1;
  led_init.Mode  = GPIO_MODE_OUTPUT_PP;
  led_init.Pull  = GPIO_NOPULL;
  led_init.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &led_init);

  // 3. 默认将 RS485 设为接收模式，确保上电后不会导致总线冲突
  Set_RS485_Direction(0);

  // 4. 初始化指示灯状态：两个灯都关闭 (低电平点亮)
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, GPIO_PIN_SET);   // 绿灯灭
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_1, GPIO_PIN_SET);   // 红灯灭

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
    //   动作1: 云台左转(速度0x1E=30) → 保持3秒 → LED闪烁
    //   动作2: 云台停止 → 保持2秒   → LED闪烁
    //   动作3: 云台仰头(速度0x14=20) → 保持3秒 → LED闪烁
    //   动作4: 云台停止 → 保持2秒   → LED闪烁
    // 循环往复，每步均通过 PelcoD_Control_And_Query 发送指令并接收云台反馈

    uint8_t rx_buf[16];
    uint8_t rx_len = 0;

    // ----- 动作1: 左转 (命令码0x04, 水平速度30) -----
    printf("[系统] === 动作1: 云台左转(速度30) ===\r\n");
    LED_Toggle_Once();
    PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_PAN_LEFT,
                             30, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
    HAL_Delay(3000);  // 保持左转3秒，期间云台持续执行

    // ----- 动作2: 停止 -----
    printf("[系统] === 动作2: 云台停止 ===\r\n");
    LED_Toggle_Once();
    PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_STOP,
                             0x00, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
    HAL_Delay(2000);  // 停止保持2秒

    // ----- 动作3: 仰头 (命令码0x08, 垂直速度20) -----
    printf("[系统] === 动作3: 云台仰头(速度20) ===\r\n");
    LED_Toggle_Once();
    PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_TILT_UP,
                             0x00, 20, rx_buf, &rx_len, RX_TIMEOUT_MS);
    HAL_Delay(3000);  // 保持仰头3秒

    // ----- 动作4: 停止 -----
    printf("[系统] === 动作4: 云台停止 ===\r\n");
    LED_Toggle_Once();
    PelcoD_Control_And_Query(PTZ_ADDR_DEFAULT, 0x00, PELCOD_CMD_STOP,
                             0x00, 0x00, rx_buf, &rx_len, RX_TIMEOUT_MS);
    HAL_Delay(2000);  // 停止保持2秒

    // 一个完整测试周期结束后，打印分隔线，便于观察电脑端串口输出
    printf("\r\n[系统] ---- 一个测试周期完成，休息1秒后开始下一周期 ----\r\n\r\n");
    HAL_Delay(1000);

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
 * @brief  微秒级延时函数 (使用 DWT Cycle Count 实现高精度延时)
 * @param  us: 延时微秒数
 * @note   需要在 CoreDebug->DEMCR 中使能 TRCENA，DWT->CYCCNT 必须未禁用
 *         STM32H7 默认情况下 DWT 可直接使用，无需额外配置
 */
void delay_us(uint32_t us)
{
    uint32_t cycles = us * (SystemCoreClock / 1000000U);
    uint32_t start = DWT->CYCCNT;
    while ((DWT->CYCCNT - start) < cycles) {
        // 空循环等待
    }
}

/**
 * @brief  重定向 printf 到 USART1
 * @note   不依赖 MicroLIB，禁用半主机避免卡死
 */
#if defined(__MICROLIB)
// 微库模式：实现 fputc
__attribute__((weak)) int fputc(int ch, FILE *f)
{
    (void)f;
    HAL_UART_Transmit(&huart1, (uint8_t *)&ch, 1, 10);
    return ch;
}
#else
// 标准库模式：实现 __io_putchar
int __io_putchar(int ch)
{
    HAL_UART_Transmit(&huart1, (uint8_t *)&ch, 1, 10);
    return ch;
}

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