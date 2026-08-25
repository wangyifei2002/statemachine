#ifndef APP_FORMAT_H
#define APP_FORMAT_H

#include <stdarg.h>
#include <stdint.h>

uint16_t App_FormatV(char *buffer,
                     uint16_t buffer_size,
                     const char *format,
                     va_list args);
uint16_t App_Format(char *buffer,
                    uint16_t buffer_size,
                    const char *format,
                    ...);

#endif
