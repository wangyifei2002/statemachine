#include "fsm.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LINE_SIZE 1024
#define COLUMN_COUNT 17

static int split(char *line, char **columns)
{
    int count = 0;
    char *token = strtok(line, ",\r\n");
    while ((token != NULL) && (count < COLUMN_COUNT)) {
        columns[count++] = token;
        token = strtok(NULL, ",\r\n");
    }
    return count;
}

static void fill_input(char **c, fsm_input_t *input)
{
    memset(input, 0, sizeof(*input));
    input->slot_id = (uint32_t)strtoul(c[0], NULL, 10);
    input->start = (uint8_t)atoi(c[1]);
    input->reset = (uint8_t)atoi(c[2]);
    input->mmwave_online = (uint8_t)atoi(c[3]);
    input->thz_online = (uint8_t)atoi(c[4]);
    input->gimbal_online = (uint8_t)atoi(c[5]);
    input->target_meta.valid = 1U;
    input->target_meta.seq = input->slot_id;
    input->target_valid = (uint8_t)atoi(c[6]);
    input->target_azimuth_mdeg = (int32_t)strtol(c[7], NULL, 10);
    input->target_elevation_mdeg = (int32_t)strtol(c[8], NULL, 10);
    input->gimbal_meta.valid = 1U;
    input->gimbal_meta.seq = input->slot_id;
    input->gimbal_in_position = (uint8_t)atoi(c[9]);
    input->position_error_mdeg = (int32_t)strtol(c[10], NULL, 10);
    input->thz_meta.valid = 1U;
    input->thz_meta.seq = input->slot_id;
    input->thz_locked = (uint8_t)atoi(c[11]);
    input->thz_quality = (uint16_t)strtoul(c[12], NULL, 10);
    input->mmwave_link_meta.valid = 1U;
    input->mmwave_link_meta.seq = input->slot_id;
    input->mmwave_uplink_ready = (uint8_t)atoi(c[13]);
    input->mmwave_quality = (uint16_t)strtoul(c[14], NULL, 10);
}

static int run_file(const char *path)
{
    FILE *file = fopen(path, "r");
    char line[LINE_SIZE];
    char *columns[COLUMN_COUNT];
    fsm_context_t ctx;
    fsm_input_t input;
    fsm_output_t output;
    int line_number = 1;
    if (file == NULL) {
        perror(path);
        return 1;
    }
    Fsm_Init(&ctx, NULL);
    (void)fgets(line, sizeof(line), file);
    while (fgets(line, sizeof(line), file) != NULL) {
        const char *expected_state;
        const char *expected_reason;
        line_number++;
        if (split(line, columns) != COLUMN_COUNT) {
            fprintf(stderr, "%s:%d invalid column count\n", path, line_number);
            fclose(file);
            return 1;
        }
        fill_input(columns, &input);
        expected_state = columns[15];
        expected_reason = columns[16];
        Fsm_Step(&ctx, &input, &output);
        if ((strcmp(Fsm_StateName(output.state), expected_state) != 0) ||
            (strcmp(Fsm_ReasonName(output.reason), expected_reason) != 0)) {
            fprintf(stderr, "%s:%u got %s/%s expected %s/%s\n", path,
                    input.slot_id, Fsm_StateName(output.state), Fsm_ReasonName(output.reason),
                    expected_state, expected_reason);
            fclose(file);
            return 1;
        }
        printf("{\"slot_id\":%u,\"previous_state\":\"%s\",\"state\":\"%s\","
               "\"reason\":\"%s\",\"fault_mask\":%u}\n",
               input.slot_id, Fsm_StateName(output.previous_state), Fsm_StateName(output.state),
               Fsm_ReasonName(output.reason), output.fault_mask);
    }
    fclose(file);
    return 0;
}

int main(int argc, char **argv)
{
    int i;
    int status = 0;
    if (argc < 2) {
        fprintf(stderr, "usage: %s scenario.csv [...]\n", argv[0]);
        return 2;
    }
    for (i = 1; i < argc; i++) {
        if (run_file(argv[i]) != 0) {
            status = 1;
        }
    }
    return status;
}
