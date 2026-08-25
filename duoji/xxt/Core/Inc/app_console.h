#ifndef APP_CONSOLE_H
#define APP_CONSOLE_H

#include "stm32h7xx_hal.h"

void App_Console_Init(UART_HandleTypeDef *huart);
void App_Console_Poll(void);
void App_Console_SendLine(const char *text);

#endif
