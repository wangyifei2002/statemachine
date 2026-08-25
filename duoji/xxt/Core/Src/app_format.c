#include "app_format.h"

typedef struct
{
    char *buffer;
    uint16_t size;
    uint16_t length;
} format_output_t;

static void output_char(format_output_t *output, char value)
{
    if ((output->size > 0U) &&
        (output->length < (uint16_t)(output->size - 1U)))
    {
        output->buffer[output->length] = value;
    }
    if (output->length < 0xFFFFU)
    {
        output->length++;
    }
}

static void output_string(format_output_t *output, const char *text)
{
    if (text == 0)
    {
        text = "(null)";
    }
    while (*text != '\0')
    {
        output_char(output, *text++);
    }
}

static void output_unsigned(format_output_t *output,
                            uint32_t value,
                            uint32_t base,
                            uint8_t uppercase,
                            uint8_t negative,
                            uint8_t width,
                            char padding)
{
    char digits[11];
    uint8_t count = 0U;
    uint8_t total;
    uint32_t digit;

    do
    {
        digit = value % base;
        value /= base;
        if (digit < 10U)
        {
            digits[count++] = (char)('0' + digit);
        }
        else
        {
            digits[count++] = (char)((uppercase ? 'A' : 'a') +
                                     (digit - 10U));
        }
    } while ((value != 0U) && (count < sizeof(digits)));

    total = (uint8_t)(count + (negative ? 1U : 0U));
    if (negative && (padding == '0'))
    {
        output_char(output, '-');
        negative = 0U;
    }
    while (total < width)
    {
        output_char(output, padding);
        total++;
    }
    if (negative)
    {
        output_char(output, '-');
    }
    while (count > 0U)
    {
        output_char(output, digits[--count]);
    }
}

uint16_t App_FormatV(char *buffer,
                     uint16_t buffer_size,
                     const char *format,
                     va_list args)
{
    format_output_t output;

    output.buffer = buffer;
    output.size = buffer_size;
    output.length = 0U;

    if ((buffer == 0) || (format == 0))
    {
        return 0U;
    }

    while (*format != '\0')
    {
        uint8_t width = 0U;
        uint8_t long_value = 0U;
        char padding = ' ';
        char specifier;

        if (*format != '%')
        {
            output_char(&output, *format++);
            continue;
        }
        format++;
        if (*format == '%')
        {
            output_char(&output, *format++);
            continue;
        }
        if (*format == '0')
        {
            padding = '0';
            format++;
        }
        while ((*format >= '0') && (*format <= '9'))
        {
            width = (uint8_t)((width * 10U) +
                              (uint8_t)(*format - '0'));
            format++;
        }
        if (*format == 'l')
        {
            long_value = 1U;
            format++;
        }

        specifier = *format;
        if (specifier == '\0')
        {
            break;
        }
        format++;

        switch (specifier)
        {
        case 's':
            output_string(&output, va_arg(args, const char *));
            break;

        case 'c':
            output_char(&output, (char)va_arg(args, int));
            break;

        case 'd':
        case 'i':
        {
            int32_t signed_value;
            uint32_t magnitude;
            uint8_t negative;

            signed_value = long_value ?
                           (int32_t)va_arg(args, long) :
                           (int32_t)va_arg(args, int);
            negative = (signed_value < 0) ? 1U : 0U;
            magnitude = negative ?
                        (uint32_t)(-(signed_value + 1)) + 1U :
                        (uint32_t)signed_value;
            output_unsigned(&output, magnitude, 10U, 0U,
                            negative, width, padding);
            break;
        }

        case 'u':
        case 'x':
        case 'X':
        {
            uint32_t value;

            value = long_value ?
                    (uint32_t)va_arg(args, unsigned long) :
                    (uint32_t)va_arg(args, unsigned int);
            output_unsigned(&output,
                            value,
                            (specifier == 'u') ? 10U : 16U,
                            (specifier == 'X') ? 1U : 0U,
                            0U, width, padding);
            break;
        }

        default:
            output_char(&output, '?');
            break;
        }
    }

    if (buffer_size > 0U)
    {
        uint16_t terminator = output.length;
        if (terminator >= buffer_size)
        {
            terminator = (uint16_t)(buffer_size - 1U);
        }
        buffer[terminator] = '\0';
    }
    return output.length;
}

uint16_t App_Format(char *buffer,
                    uint16_t buffer_size,
                    const char *format,
                    ...)
{
    uint16_t length;
    va_list args;

    va_start(args, format);
    length = App_FormatV(buffer, buffer_size, format, args);
    va_end(args);
    return length;
}
